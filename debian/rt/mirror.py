import apt_pkg
import itertools
import os

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

