import apt_pkg

from debian.rt.package import (SourcePackage, BinaryPackage)


def binary_has_external_rdeps(source, binary, bin_suite):
    if binary in bin_suite:
        for rdep in bin_suite[binary].reverse_depends:
            if rdep.source != source:
                return True
    return False


def as_ben_file(transition_name, new_binaries, old_binaries, extra_info):
    good = '|'.join(new_binaries)
    bad = '|'.join(old_binaries)
    extra_notes = ''
    if good:
        affected = '|'.join((good, bad))
        good = ".depends ~ /%s/" % good
    else:
        good = "false"
        affected = bad
    if extra_info:
        extra_notes = '\n\nExtra information (collected entirely from testing!):\n'
        extra_notes = extra_notes + "\n".join(" * %s: %s" % (key, str(extra_info[key])) for key in sorted(extra_info))
    return """\
title = "{transition_name} (auto)";
is_affected = .depends ~ /{affected}/;
is_good = {good};
is_bad = .depends ~ /{bad}/;
notes = "This tracker was setup by a very simple automated tool.  The tool may not be very smart...{extra_notes}";
""".format(transition_name=transition_name, good=good, bad=bad, affected=affected, extra_notes=extra_notes)


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
                architecture=get_field('Architecture'),
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
    return
