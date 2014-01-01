#!/usr/bin/python

import apt_pkg
import itertools
import os
import sys

class BasePackage(object):
    def __init__(self, **kwargs):
        for key in kwargs:
            setattr(self, key, kwargs[key])


class SourcePackage(BasePackage):
    pass


class BinaryPackage(BasePackage):
    pass


class PackageMirrorDist(object):
    def __init__(self, mirror_dist_path):
        self.mirror_dist_path = mirror_dist_path

        release_file = os.path.join(mirror_dist_path, "Release")
        tag_file = apt_pkg.TagFile(release_file)
        if not tag_file.step():
            raise IOError("Empty Release file (no paragraphs): %s " % release_file)

        self.components = tag_file.section['Components'].split()
        self.architectures = tag_file.section['Architectures'].split()

    @property
    def packages_files(self):
        for comp, arch in itertools.product(self.components, self.architectures):
            yield os.path.join(self.mirror_dist_path, comp, "binary-%s" % arch, "Packages.gz")

    @property
    def sources_files(self):
        for comp in self.components:
            yield os.path.join(self.mirror_dist_path, comp, "source", "Sources.gz")


def read_sources(mirror_dist, intern=intern):
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


def read_binaries(mirror_dist, intern=intern):
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


    for pkg_name in packages:
        pkg = packages[pkg_name]
        for ordep in pkg.depends:
            for dep in ordep:
                dep_pkg = dep[0]
                if dep_pkg not in packages:
                    continue
                packages[dep_pkg].reverse_depends.add(pkg)

    return packages


def compute_reverse_dependencies(packages):
    for pkg in packages:
        pass


def transitions(src_test, src_sid):
    for source in sorted(src_test):
        if source not in src_sid:
            continue
        test_bin = src_test[source]
        sid_bin = src_sid[source]

        if test_bin.binaries <= sid_bin.binaries:
            continue

        new_bin = sorted(x for x in sid_bin.binaries - test_bin.binaries)
        old_bin = sorted(x for x in test_bin.binaries - sid_bin.binaries)

        yield (source, new_bin, old_bin)

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


def _crap(source, new_binaries, old_binaries):
    print source
    for b in new_binaries:
        print " + %s" % b
#            print " + %s (%s)" % (b.package, b.section)
    for b in old_binaries:
        print " - %s" % b
#            print " - %s (%s)" % (b.package, b.section)


if __name__ == "__main__":
    apt_pkg.init()

    mirror_test = PackageMirrorDist(sys.argv[1])
    mirror_sid = PackageMirrorDist(sys.argv[2])

    src_test = read_sources(mirror_test)
    src_sid = read_sources(mirror_sid)

    destdir = None
    if len(sys.argv) >= 4:
        destdir = sys.argv[3]

    possible_transitions = list(transitions(src_test, src_sid))

    if not possible_transitions:
        exit(0)

#    bin_test = read_binaries(mirror_test)
    bin_sid = read_binaries(mirror_sid)

    for source, new_binaries, old_binaries in possible_transitions:
        output = as_ben_file(source, new_binaries, old_binaries)
        has_rdeps = False
        if not new_binaries:
            continue

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
            filename = "auto-%s.ben" % source
            path = os.path.join(destdir, filename)
            with open(path, "w") as fd:
                fd.write(output)
        else:
            sys.stdout.write(output)
