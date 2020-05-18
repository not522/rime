import os.path

from rime.core import consts
from rime.util import files


class ProblemComponentMixin(object):
    """Mix-in for components of a problem (solution, testset)."""

    def __init__(self):
        self.src_dir = self.base_dir
        assert self.src_dir.startswith(self.base_dir)
        rel_dir = self.src_dir[len(self.problem.base_dir) + 1:]
        self.out_dir = os.path.join(self.problem.out_dir, rel_dir)
        self.stamp_file = os.path.join(self.out_dir, consts.STAMP_FILE)

    def GetLastModified(self):
        """Get timestamp of this target."""
        stamp = files.GetLastModifiedUnder(self.src_dir)
        if self.project.library_dir is not None:
            stamp = max(stamp, files.GetLastModifiedUnder(
                self.project.library_dir))
        return stamp

    def SetCacheStamp(self, ui):
        """Update the stamp file."""
        try:
            files.CreateEmptyFile(self.stamp_file)
            return True
        except Exception:
            ui.errors.Exception(self)
            return False

    def GetCacheStamp(self):
        """Get timestamp of the stamp file.

        Returns datetime.datetime.min if not available.
        """
        return files.GetModified(self.stamp_file)

    def IsBuildCached(self):
        """Check if cached build is not staled."""
        src_mtime = self.GetLastModified()
        stamp_mtime = self.GetCacheStamp()
        return (src_mtime < stamp_mtime)
