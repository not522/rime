from __future__ import with_statement
import datetime
import os
import os.path
import platform
import shutil
import subprocess


_devnull = open(os.devnull, 'r+')


def CopyFile(src, dst):
    shutil.copy(src, dst)


def MakeDir(dir):
    if not os.path.isdir(dir):
        os.makedirs(dir)


def CopyTree(src, dst):
    MakeDir(dst)
    files = ListDir(src, True)
    for f in files:
        srcpath = os.path.join(src, f)
        dstpath = os.path.join(dst, f)
        if os.path.isdir(srcpath):
            MakeDir(dstpath)
        else:
            CopyFile(srcpath, dstpath)


def RemoveTree(dir):
    if os.path.exists(dir):
        shutil.rmtree(dir)


def GetModified(file):
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(file))
    except Exception:
        return datetime.datetime.min


def GetLastModifiedUnder(dir):
    file_list = [f for f in ListDir(dir, True)] + [dir]
    return max([GetModified(os.path.join(dir, name)) for name in file_list])


def CreateEmptyFile(file):
    open(file, 'w').close()


def ListDir(dir, recursive=False):
    files = []
    try:
        files = filter(lambda x: not x.startswith('.'),
                       os.listdir(dir))
        if recursive:
            for subfile in files[:]:
                subdir = os.path.join(dir, subfile)
                if os.path.isdir(subdir):
                    files += [os.path.join(subfile, s)
                              for s in ListDir(subdir, True)]
    except Exception:
        pass
    return files


def ConvPath(path):
    if not platform.uname()[0].lower().startswith('cygwin'):
        return path
    try:
        p = subprocess.Popen(['cygpath', '-wp', path], stdout=subprocess.PIPE)
        newpath = p.communicate()[0].rstrip('\r\n')
        if p.returncode == 0:
            return newpath
    except Exception:
        pass
    return path


def OpenNull():
    return _devnull


def ReadFile(name):
    try:
        with open(name, 'r') as f:
            return f.read()
    except Exception:
        return None


def WriteFile(content, name):
    try:
        with open(name, 'w') as f:
            f.write(content)
        return True
    except Exception:
        return False
