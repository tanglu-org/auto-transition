#!/usr/bin/python

import apt_pkg
import copy
import itertools
import os
import sys

from debian.rt.package import (SourcePackage, BinaryPackage)
from debian.rt.mirror import PackageMirrorDist
from debian.rt.util import (binary_has_external_rdeps,
                            as_ben_file, compute_reverse_dependencies,
                            read_sources, read_binaries
                           )


def find_nearly_finished_transitions(src_test, bin_test, stage):
    src2bin = {}
    for bin_pkg in bin_test.itervalues():
        if bin_pkg.architecture == 'all':
            continue
        source_pkg = src_test.get(bin_pkg.source, None)
        if source_pkg is None:
            src2bin.setdefault(bin_pkg.source, set())
            src2bin[bin_pkg.source].add(bin_pkg.package)
            continue
        if apt_pkg.version_compare(source_pkg.version, bin_pkg.source_version) > 0:
            src2bin.setdefault(bin_pkg.source, set())
            src2bin[bin_pkg.source].add(bin_pkg.package)

    for source in sorted(src2bin):
        extra_info = {}
        source_pkg = src_test[source]
        new_bin = sorted(x for x in source_pkg.binaries - src2bin[source])
        old_bin = sorted(x for x in src2bin[source] - source_pkg.binaries)

        yield (source, source, new_bin, old_bin, stage, extra_info)


def transitions(src_test, bin_test, src_new, stage):
    for source in sorted(src_test):
        transition_name = source
        test_bin = src_test[source].binaries
        if source in src_new:
            new_suite_bin = src_new[source].binaries
        else:
            transition_name = source + "-rm"
            new_suite_bin = set()
            if not any(y for x in test_bin if x in bin_test
                         for y in bin_test[x].reverse_depends
                             if y.package not in test_bin):
                continue

        if test_bin <= new_suite_bin:
            continue

        new_bin = sorted(x for x in new_suite_bin - test_bin)
        old_bin = sorted(x for x in test_bin - new_suite_bin)
        extra_info = {}
        extra_info['can-smooth-update'] = 'maybe'

        for old_pkg in old_bin:
            if old_pkg not in bin_test:
                # happens with udebs
                continue
            old_pkg_data = bin_test[old_pkg]
            if old_pkg_data.section not in ('libs', 'oldlibs'):
                if old_pkg_data.reverse_depends:
                    extra_info['can-smooth-update'] = 'no - %s is not in libs or oldlibs' % old_pkg
                elif extra_info['can-smooth-update'] == 'maybe':
                    extra_info['can-smooth-update'] = 'maybe (ignoring rdep-less binaries)'

        yield (transition_name, source, new_bin, old_bin, stage, extra_info)


def find_existing_transitions(destdir):
    transitions = {}
    for stage in ("planned", "ongoing", "finished"):
        stagedir = os.path.join(destdir, stage)
        transitions[stage] = set()
        for basename in os.listdir(stagedir):
            if basename.endswith(".ben"):
                transitions[stage].add(basename[:-4])
                if basename.endswith("-rm.ben"):
                    transitions[stage].add(basename[:-7])

    return transitions


if __name__ == "__main__":
    apt_pkg.init()

    seen = set()

    mirror_test = PackageMirrorDist(sys.argv[1])
    mirror_sid = PackageMirrorDist(sys.argv[2])
    mirror_exp = PackageMirrorDist(sys.argv[3])
    destdir = sys.argv[4]

    src_test = read_sources(mirror_test)
    src_sid = read_sources(mirror_sid)
    src_exp = read_sources(mirror_exp, src_sid.copy())

    bin_test = read_binaries(mirror_test)

    compute_reverse_dependencies(bin_test)

    possible_transitions = list(transitions(src_test, bin_test, src_sid, 'ongoing'))
    possible_transitions.extend(transitions(src_test, bin_test, src_exp, 'planned'))
    possible_transitions.extend(find_nearly_finished_transitions(
            src_test, bin_test, 'finished'))

    existing_tranistions = find_existing_transitions(destdir)
    possible_transitions = [x for x in possible_transitions
                            if x[0] not in existing_tranistions[x[4]] ]

    if not possible_transitions:
        exit(0)

    bin_sid = read_binaries(mirror_sid)
    bin_exp = read_binaries(mirror_exp, copy.deepcopy(bin_sid))

    compute_reverse_dependencies(bin_sid)
    compute_reverse_dependencies(bin_exp)
    transition_data = {}

    for transition_name, source, new_binaries, old_binaries, stage, extra_info in possible_transitions:

        if not new_binaries and stage != 'finished' and transition_name == source:
            continue

        bin_suite = bin_sid
        if stage == 'finished':
            bin_suite = bin_test

        if old_binaries and new_binaries:
            old_has_rdeps = False
            new_has_rdeps = False
            for binary in old_binaries:
                if binary_has_external_rdeps(source, binary, bin_suite):
                    old_has_rdeps = True
                    break

            if not old_has_rdeps:
                for binary in new_binaries:
                    if binary_has_external_rdeps(source, binary, bin_suite):
                        new_has_rdeps = True
                        break
            if not old_has_rdeps and not new_has_rdeps:
                # No rdeps seem affected, skip...
                continue

        if transition_name in seen:
            # If there is a planned and an ongoing, focus on the
            # ongoing transition.  NB: We rely here on the order of
            # possible_transition
            continue
        seen.add(transition_name)


        if destdir:
            output = as_ben_file(transition_name, new_binaries, old_binaries, extra_info)
            filename = "auto-%s.ben" % transition_name
            path = os.path.join(destdir, stage, filename)
            with open(path, "w") as fd:
                fd.write(output)

