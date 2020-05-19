import functools
import os
import signal
import subprocess
import sys
import threading
import time

from six import reraise


class TaskBranch(object):
    def __init__(self, tasks):
        self.tasks = tasks


class TaskReturn(object):
    def __init__(self, value):
        self.value = value


class TaskBlock(object):
    pass


class _TaskRaise(object):
    """Internal only; don't return an instance of this class from generators"""

    def __init__(self, type, value=None, traceback=None):
        self.exc_info = (type, value, traceback)


class Bailout(Exception):
    def __init__(self, value=None):
        self.value = value


class Task(object):
    def __hash__(self):
        """Hash function of Task.

        Usually users should override CacheKey() only.
        """
        if self.CacheKey() is None:
            return id(self)
        return hash(self.CacheKey())

    def __eq__(self, other):
        """Equality function of Task.

        Usually users should override CacheKey() only.
        """
        if not isinstance(other, Task):
            return False
        if self.CacheKey() is None and other.CacheKey() is None:
            return id(self) == id(other)
        return self.CacheKey() == other.CacheKey()

    def CacheKey(self):
        """Returns the cache key of this task.

        Need to be overridden in subclasses.
        If this returns None, the task value is never cached.
        """
        raise NotImplementedError()

    def Continue(self, value=None):
        """Continues the task.

        Implementations can return these type of values:
        - TaskBranch: a list of tasks to be invoked next.
        - TaskReturn: a value to be returned to the caller.
        - TaskBlock: indicates this operation will block.
        - Task: treated as TaskBranch(task).
        - any other value: treated as TaskReturn(value).
        In addition to these, it can raise an exception, including Bailout.

        First invocation of this function will be with no parameter or None.
        If it returns TaskBranch, next parameter will be a list of the results
        of the specified tasks.
        """
        raise NotImplementedError()

    def Throw(self, type, value=None, traceback=None):
        """Throws in an exception.

        After Continue() or Throw() returned TaskBranch, if some of the
        branches raised an exception, this function is called. Return
        value of this function is treated in the same way as Continue().
        """
        raise NotImplementedError()

    def Poll(self):
        """Polls the blocked task.

        If the operation is ready, return True. This function should return
        immediately, and should not raise an exception.
        """
        return True

    def Wait(self):
        """Polls the blocked task.

        This function should wait until the operation gets ready. This function
        should not raise an exception.
        """
        pass

    def Close(self):
        """Closes the task.

        This is called once after Continue() or Throw() returned TaskReturn,
        they raised an exception, or the task was interrupted.
        The task should release all resources associated with it, such as
        running generators or opened processes.
        If this function raises an exception, the value returned by Continue()
        or Throw() is discarded.
        """
        pass


class GeneratorTask(Task):
    def __init__(self, it, key):
        self.it = it
        self.key = key

    def __repr__(self):
        return repr(self.key)

    def CacheKey(self):
        return self.key

    def Continue(self, value=None):
        try:
            return self.it.send(value)
        except StopIteration:
            return TaskReturn(None)

    def Throw(self, type, value=None, traceback=None):
        try:
            return self.it.throw(type, value, traceback)
        except StopIteration:
            return TaskReturn(None)

    def Close(self):
        try:
            self.it.close()
        except RuntimeError:
            # Python2.5 raises RuntimeError when GeneratorExit is ignored.
            # This often happens when yielding a return value from inside
            # of try block, or even Ctrl+C was pressed when in try block.
            pass

    @staticmethod
    def FromFunction(func):
        @functools.wraps(func)
        def MakeTask(*args, **kwargs):
            key = GeneratorTask._MakeCacheKey(func, args, kwargs)
            try:
                hash(key)
            except TypeError:
                raise ValueError(
                    'Unhashable argument was passed to GeneratorTask function')
            it = func(*args, **kwargs)
            return GeneratorTask(it, key)
        return MakeTask

    @staticmethod
    def _MakeCacheKey(func, args, kwargs):
        return ('GeneratorTask', func, tuple(args), tuple(kwargs.items()))


# Shortcut for daily use.
task_method = GeneratorTask.FromFunction


class ExternalProcessTask(Task):
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.proc = None
        if 'timeout' in kwargs:
            self.timeout = kwargs['timeout']
            del kwargs['timeout']
        else:
            self.timeout = None
        if 'exclusive' in kwargs:
            self.exclusive = kwargs['exclusive']
            del kwargs['exclusive']
        else:
            self.exclusive = False
        self.timer = None

    def CacheKey(self):
        # Never cache.
        return None

    def Continue(self, value=None):
        if self.exclusive:
            return self._ContinueExclusive()
        else:
            return self._ContinueNonExclusive()

    def _ContinueExclusive(self):
        assert self.proc is None
        self._StartProcess()
        self.proc.wait()
        return TaskReturn(self._EndProcess())

    def _ContinueNonExclusive(self):
        if self.proc is None:
            self._StartProcess()
            return TaskBlock()
        elif not self.Poll():
            return TaskBlock()
        else:
            return TaskReturn(self._EndProcess())

    def Poll(self):
        assert self.proc is not None
        return self.proc.poll() is not None

    def Wait(self):
        assert self.proc is not None
        self.proc.wait()

    def Close(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if self.proc is not None:
            try:
                os.kill(self.proc.pid, signal.SIGKILL)
            except Exception:
                pass
            self.proc.wait()
            self.proc = None

    def _StartProcess(self):
        self.start_time = time.time()
        self.proc = subprocess.Popen(*self.args, **self.kwargs)
        if self.timeout is not None:
            def TimeoutKiller():
                try:
                    os.kill(self.proc.pid, signal.SIGXCPU)
                except Exception:
                    pass
            self.timer = threading.Timer(self.timeout, TimeoutKiller)
            self.timer.start()
        else:
            self.timer = None

    def _EndProcess(self):
        self.end_time = time.time()
        self.time = self.end_time - self.start_time
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        # Don't keep proc in cache.
        proc = self.proc
        self.proc = None
        return proc


class SerialTaskGraph(object):
    """TaskGraph which emulates normal serialized execution."""

    def __init__(self):
        self.cache = dict()
        self.running = False

    def Run(self, task):
        assert not self.running
        self.running = True
        try:
            return self._Run(task)
        finally:
            self.running = False

    def _Run(self, task):
        if task not in self.cache:
            self.cache[task] = None
            value = (True, None)
            while True:
                try:
                    if value[0]:
                        result = task.Continue(value[1])
                    elif isinstance(value[1][1], Bailout):
                        result = task.Continue(value[1][1].value)
                    else:
                        result = task.Throw(*value[1])
                except StopIteration:
                    result = TaskReturn(None)
                except Exception:
                    result = _TaskRaise(*sys.exc_info())
                if isinstance(result, TaskBranch):
                    try:
                        value = (True, [self._Run(subtask)
                                        for subtask in result.tasks])
                    except Exception:
                        value = (False, sys.exc_info())
                elif isinstance(result, Task):
                    try:
                        value = (True, self._Run(result))
                    except Exception:
                        value = (False, sys.exc_info())
                elif isinstance(result, TaskBlock):
                    value = (True, None)
                    task.Wait()
                elif isinstance(result, _TaskRaise):
                    self.cache[task] = (False, result.exc_info)
                    break
                elif isinstance(result, TaskReturn):
                    self.cache[task] = (True, result.value)
                    break
                else:
                    self.cache[task] = (True, result)
                    break
            try:
                task.Close()
            except Exception:
                self.cache[task] = (False, sys.exc_info())
        if self.cache[task] is None:
            raise RuntimeError('Cyclic task dependency found')
        success, value = self.cache[task]
        if success:
            return value
        else:
            reraise(value[0], value[1], value[2])
