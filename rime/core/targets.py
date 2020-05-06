import os
import os.path
from subprocess import call

from rime.util import class_registry
from rime.util import files


class TargetBase(object):
    """Base class of all target types."""

    # Config filename of this target.  Every subclass should override this.
    CONFIG_FILENAME = None

    def __init__(self, name, base_dir, parent):
        """Constructs a new unconfigured target."""
        self.name = name
        self.base_dir = base_dir
        self.parent = parent

        # Set full name.
        # Full name is normally path-like string separated with "/".
        if name is None:
            self.name = '<root>'
            self.fullname = None
        elif parent is None or parent.fullname is None:
            self.fullname = name
        else:
            self.fullname = parent.fullname + '/' + name

        # Locate config file.
        self.config_file = os.path.join(base_dir, self.CONFIG_FILENAME)

        self.exports = {}
        self.configs = {}

        self._loaded = False

    def Load(self, ui):
        """Loads configurations and do setups.

        Raises:
          ConfigurationError: configuration is missing or incorrect.
        """
        assert not self._loaded, 'TargetBase.Load() called twice!'
        self._loaded = True

        # Evaluate config.
        try:
            script = files.ReadFile(self.config_file)
        except IOError:
            raise ConfigurationError('cannot read file: %s' % self.config_file)
        try:
            self.PreLoad(ui)
            if self.config_file[-5:] != '.json':
                code = compile(script, self.config_file, 'exec')
                exec(code, self.exports, self.configs)
            self.PostLoad(ui)
        except Exception as e:
            # TODO(nya): print pretty file/lineno for debug
            raise ConfigurationError(e)

    def FindByBaseDir(self, base_dir):
        """Search whole subtree and return the object with matching base_dir.

        Subclasses may want to override this method for recursive search.
        """
        if self.base_dir == base_dir:
            return self
        return None

    @classmethod
    def CanLoadFrom(self, base_dir):
        return os.path.isfile(os.path.join(base_dir, self.CONFIG_FILENAME))


class ConfigurationError(Exception):
    pass


libdir = None


def EditFile(filename, initial):
    EDITOR = os.environ.get('EDITOR', 'vi')
    files.WriteFile(initial, filename)
    call([EDITOR, filename])


registry = class_registry.ClassRegistry(TargetBase)
