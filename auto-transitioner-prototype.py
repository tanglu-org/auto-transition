#!/usr/bin/python

import apt_pkg
import copy
import itertools
import os
import sys

from debian.rt.package import (SourcePackage, BinaryPackage)
from debian.rt.mirror import PackageMirrorDist


def read_sources(mirror_dist, sources=None, intern=intern):
    if sources is None:
        sources = {}

    for filename in mirror_dist.sources_files:
        tag_file = apt_pkg.TagFile(filename)
        get_field = tag_file.section.get
        step = tag_file.step

        while step():
            if get_field('Extra-Source-Only', 'no') == 'yes':
                # Ignore sources only referenced by Built-Using
                continue
            pkg = intern(get_field('Package'))
            ver = intern(get_field('Version'))

            if pkg in sources and apt_pkg.version_compare(sources[pkg].version, ver) > 0:
                continue

            binaries = frozenset(x.strip() for x in get_field('Binary').split(','))

            sources[pkg] = SourcePackage(
                source=pkg,
                package=pkg,
                version=ver,
                source_version=ver,
                binaries=binaries,
            )

    return sources


def read_binaries(mirror_dist, packages=None, intern=intern):
    if packages is None:
        packages = {}

    for filename in mirror_dist.packages_files:
        tag_file = apt_pkg.TagFile(filename)
        get_field = tag_file.section.get
        step = tag_file.step

        while step():
            pkg = intern(get_field('Package'))
            version = intern(get_field('Version'))
            source = get_field('Source', pkg)
            source_version = version

            # There may be multiple versions of any arch:all packages
            # (in unstable) if some architectures have out-of-date
            # binaries.
            if pkg in packages and apt_pkg.version_compare(packages[pkg].version, version) > 0:
                continue

            if "(" in source:
                source, v = (x.strip() for x in source.split("("))
                v.rstrip(" )")
                source = intern(source)
                source_version = intern(v)

            section = intern(get_field('Section', 'N/A'))

            depends_field = get_field('Depends')
            predepends_field = get_field('Pre-Depends')
            depends = []
            if depends_field:
                depends.extend(apt_pkg.parse_depends(depends_field))
            if predepends_field:
                depends.extend(apt_pkg.parse_depends(predepends_field))

            bin_pkg = BinaryPackage(
                package=pkg,
                version=version,
                source=source,
                source_version=source_version,
                section=section,
                depends=depends,
                reverse_depends=set(),
            )

            packages[pkg] = bin_pkg


    return packages


def compute_reverse_dependencies(packages):
    for pkg_name in packages:
        pkg = packages[pkg_name]
        for ordep in pkg.depends:
            for dep in ordep:
                dep_pkg = dep[0]
                if dep_pkg not in packages:
                    continue
                packages[dep_pkg].reverse_depends.add(pkg)


def transitions(src_test, src_new, stage):
    for source in sorted(src_test):
        if source not in src_new:
            continue
        test_bin = src_test[source]
        new_suite_bin = src_new[source]

        if test_bin.binaries <= new_suite_bin.binaries:
            continue

        new_bin = sorted(x for x in new_suite_bin.binaries - test_bin.binaries)
        old_bin = sorted(x for x in test_bin.binaries - new_suite_bin.binaries)

        yield (source, new_bin, old_bin, stage)


def as_ben_file(source, new_binaries, old_binaries):
    good = '|'.join(new_binaries)
    bad = '|'.join(old_binaries)
    affected = '|'.join((good, bad))
    return """
title = "{source} (auto)";
is_affected = .depends ~ /{affected}/;
is_good = .depends ~ /{good}/;
is_bad = .depends ~ /{bad}/;
notes = "This tracker was setup by a very simple automated tool.  The tool may not be very smart...";
""".format(source=source, good=good, bad=bad, affected=affected)


if __name__ == "__main__":
    apt_pkg.init()

    seen = set()

    mirror_test = PackageMirrorDist(sys.argv[1])
    mirror_sid = PackageMirrorDist(sys.argv[2])
    mirror_exp = PackageMirrorDist(sys.argv[3])

    src_test = read_sources(mirror_test)
    src_sid = read_sources(mirror_sid)
    src_exp = read_sources(mirror_exp, src_sid.copy())

    destdir = None
    if len(sys.argv) >= 5:
        destdir = sys.argv[4]

    possible_transitions = list(transitions(src_test, src_sid, 'ongoing'))
    possible_transitions.extend(transitions(src_test, src_exp, 'planned'))

    if not possible_transitions:
        exit(0)

    bin_sid = read_binaries(mirror_sid)
    bin_exp = read_binaries(mirror_exp, copy.deepcopy(bin_sid))

    compute_reverse_dependencies(bin_sid)
    compute_reverse_dependencies(bin_exp)
    transition_data = {}

    for source, new_binaries, old_binaries, stage in possible_transitions:
        has_rdeps = False

        if not new_binaries:
            continue

        if source in seen:
            # If there is a planned and an ongoing, focus on the
            # ongoing transition.  NB: We rely here on the order of
            # possible_transition
            continue
        seen.add(source)

        for binary in old_binaries:
            if binary in bin_sid:
                for rdep in bin_sid[binary].reverse_depends:
                    if rdep.source != source:
                        has_rdeps = True
                        break
                if has_rdeps:
                    break

        if not has_rdeps:
            continue

        if destdir:
            output = as_ben_file(source, new_binaries, old_binaries)
            filename = "auto-%s.ben" % source
            path = os.path.join(destdir, stage, filename)
            with open(path, "w") as fd:
                fd.write(output)
