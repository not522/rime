import os
import os.path
import sys

from rime.core import taskgraph
from rime.util import class_registry
from rime.util import files
from rime.util import module_loader


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
            code = compile(script, self.config_file, 'exec')
            self.PreLoad(ui)
            exec(code, self.exports, self.configs)
            self.PostLoad(ui)
        except ReloadConfiguration:
            raise  # Passthru
        except Exception as e:
            # TODO(nya): print pretty file/lineno for debug
            raise ConfigurationError(e)

    def PreLoad(self, ui):
        """Called just before evaluation of configs.

        Subclasses should setup exported symbols by self.exports.
        """
        pass

    def PostLoad(self, ui):
        """Called just after evaluation of configs.

        Subclasses can do post-processing of configs here.
        """
        pass

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


class ReloadConfiguration(Exception):
    pass


libdir = None


def EditFile(filename, initial):
    EDITOR = os.environ.get('EDITOR', 'vi')
    files.WriteFile(initial, filename)
    call([EDITOR, filename])


class Project(TargetBase):
    """Project target.

    Project is the only target defined in rime.core. Here, only special methods
    which need to be cared in the core library are defined, e.g. use_plugin().
    """

    CONFIG_FILENAME = 'PROJECT'

    def __init__(self, name, base_dir, parent):
        assert parent is None
        super(Project, self).__init__(name, base_dir, parent)
        self.project = self

    def PreLoad(self, ui):
        # Do not use super() here because targets.Project will be overridden.
        TargetBase.PreLoad(self, ui)

        def use_plugin(name):
            module_name = 'rime.plugins.%s' % name
            if module_name not in sys.modules:
                if not module_loader.LoadModule(module_name):
                    raise ConfigurationError(
                        'Failed to load a plugin: %s' % name)
                raise ReloadConfiguration('use_plugin(%s)' % repr(name))
        self.exports['use_plugin'] = use_plugin

        self.library_dir = None
        self.project_defined = False

        def _project(library_dir=None):
            if self.project_defined:
                raise RuntimeError('project() is already defined.')
            global libdir
            libdir = os.path.join(
                self.base_dir,
                library_dir)
            self.library_dir = libdir
            self.project_defined = True
        self.exports['project'] = _project

    def PostLoad(self, ui):
        super(Project, self).PostLoad(ui)
        self._ChainLoad(ui)

    def _ChainLoad(self, ui):
        # Chain-load problems.
        self.problems = []
        for name in files.ListDir(self.base_dir):
            path = os.path.join(self.base_dir, name)
            if targets.registry.Problem.CanLoadFrom(path):
                problem = targets.registry.Problem(name, path, self)
                try:
                    problem.Load(ui)
                    self.problems.append(problem)
                except targets.ConfigurationError:
                    ui.errors.Exception(problem)
        self.problems.sort(key=lambda a: (a.id, a.name))

    def FindByBaseDir(self, base_dir):
        if self.base_dir == base_dir:
            return self
        for problem in self.problems:
            obj = problem.FindByBaseDir(base_dir)
            if obj:
                return obj
        return None

    @taskgraph.task_method
    def Build(self, ui):
        """Build all problems."""
        results = yield taskgraph.TaskBranch(
            [problem.Build(ui) for problem in self.problems])
        yield all(results)

    @taskgraph.task_method
    def Test(self, ui):
        """Run tests in the project."""
        results = yield taskgraph.TaskBranch(
            [problem.Test(ui) for problem in self.problems])
        yield list(itertools.chain(*results))

    @taskgraph.task_method
    def Pack(self, ui):
        results = yield taskgraph.TaskBranch(
            [problem.Pack(ui) for problem in self.problems])
        yield all(results)

    @taskgraph.task_method
    def Upload(self, ui):
        results = yield taskgraph.TaskBranch(
            [problem.Upload(ui) for problem in self.problems])
        yield all(results)

    @taskgraph.task_method
    def Submit(self, ui):
        results = yield taskgraph.TaskBranch(
            [problem.Submit(ui) for problem in self.problems])
        yield all(results)

    @taskgraph.task_method
    def Add(self, args, ui):
        if len(args) != 2:
            yield None
        ttype = args[0].lower()
        name = args[1]
        if ttype == 'problem':
            content = '''\
pid='X'

problem(
  time_limit=1.0,
  id=pid,
  title=pid + ": Your Problem Name",
  #wiki_name="Your pukiwiki page name", # for wikify plugin
  #assignees=['Assignees', 'for', 'this', 'problem'], # for wikify plugin
  #need_custom_judge=True, # for wikify plugin
  #reference_solution='???',
  )

atcoder_config(
  task_id=None # None means a spare
)
'''
            newdir = os.path.join(self.base_dir, name)
            if(os.path.exists(newdir)):
                ui.errors.Error(self, "{0} already exists.".format(newdir))
                yield None
            os.makedirs(newdir)
            EditFile(os.path.join(newdir, 'PROBLEM'), content)
            ui.console.PrintAction('ADD', None, '%s/PROBLEM' % newdir)
        else:
            ui.errors.Error(self,
                            "Target type {0} cannot be put here.".format(
                                ttype))
            yield None

    @taskgraph.task_method
    def Clean(self, ui):
        """Clean the project."""
        results = yield taskgraph.TaskBranch(
            [problem.Clean(ui) for problem in self.problems])
        yield all(results)


registry = class_registry.ClassRegistry(TargetBase)
registry.Add(Project)
