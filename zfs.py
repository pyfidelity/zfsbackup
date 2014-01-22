#
# Copyright (c) 2010, Mij <mij@sshguard.net>
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and
#   the following disclaimer in the documentation and/or other materials provided
#   with the distribution.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
# 

#
# See http://mij.oltrelinux.com/devel/zfsbackup/
# Bitch to mij@sshguard.net
#

# module zfs
import os
import subprocess

ZFS_DEFAULT_SNAPSHOT_DIR='/.zfs/snapshot'


def pass_zfs_pool(f):
    """Decorator to pass the appropriate ZFS pool parameter at runtime, if none specified.
    Calls f(original args, zpool=value)."""
    def _decorator(*args, **kwargs):
        if 'zpool' not in kwargs.keys() or not kwargs['zpool']:
            # default to first zpool
            kwargs.update({'zpool': get_default_pool()})
        return f(*args, **kwargs)

    return _decorator


def get_pools():
    """Return a list of ZFS pools available on the system"""
    command = 'zpool list -H'
    try:
        p = subprocess.Popen(command.split(' '), stdout=subprocess.PIPE)
    except OSError:
        raise Exception('No ZFS tools found!')
    zpout, zperr = p.communicate()
    if p.returncode:
        raise Exception("Error executing '%s': %d" % (command, p.returncode))
    return [line.split('\t', 1)[0] for line in zpout.split('\n') if line]


def get_default_pool():
    """Return the primary ZFS pool configured in the system"""
    return os.environ.get('ZFS_POOL', get_pools()[0])

@pass_zfs_pool
def get_datasets(zpool=None, strip_poolname=True):
    """Return a list of ZFS datasets available in a specific pool, or in all.
    
    The root dataset is returned as an empty string."""
    if zpool and zpool not in get_pools():
        raise Exception("Pool '%s' is not available on this system!" % zpool)
    command = 'zfs list -t filesystem -H'
    try:
        p = subprocess.Popen(command.split(' '), stdout=subprocess.PIPE)
    except OSError:
        raise Exception("zfs not found. Cannot execute '%s'" % command)
    zfsout, zfserr = p.communicate()
    if p.returncode:
        print "Error executing '%s': %d" % (command, p.returncode)
        return []
    datasets = []
    for line in zfsout.split('\n'):
        dsname = line.split('\t', 1)[0]
        if not dsname: continue
        dspool, sep, mountpoint = dsname.partition('/')
        if zpool and dspool != zpool:
            continue
        if strip_poolname:
            # produce '/my/mountpoint' for children and '' for root dataset
            datasets.append(sep + mountpoint)
        else:
            datasets.append(dsname)
    return datasets


@pass_zfs_pool
def destroy_snapshot(snapname, dataset='', recursive=True, zpool=None):
    """Remove a snapshot, from root or in a specific dataset.
    
    If dataset is not specified, the snapshot is destroyed from the root.
    If a zpool is specified, remove from there; else remove from the default zpool."""
    fullsnapname = "%s%s@%s" % (zpool, dataset, snapname)
    print "Destroying snapshot '%s'" % fullsnapname
    if recursive:
        command = 'zfs destroy -r %s' % fullsnapname
    else:
        command = 'zfs destroy %s' % fullsnapname
    #print "Exec '%s'" % command
    assert command.find('@') != -1     # we are not destroying datasets, only snapshots
    p = subprocess.Popen(command.split(' '))
    p.wait()
    if p.returncode != 0 and p.returncode != 1: # 1 = snapshot did not exist. We can stand that
        raise Exception("Error executing '%s': %d" % (command, p.returncode))


@pass_zfs_pool
def take_snapshot(snapname, restrictdatasets=None, nodatasets=None, recursive=True, zpool=None):
    """Take a recursive snapshot with the given name, possibly excluding some datasets.
    
    restrictdatasets and nodatasets are optional lists of datasets to include or exclude
    from the recursive snapshot."""
    # take recursive snapshot of all datasets...
    fullsnapname = '%s@%s' % (zpool, snapname)
    print "Taking snapshot '%s'" % fullsnapname
    if restrictdatasets:
        restrictdatasets = [ds.rstrip('/') for ds in restrictdatasets]
    print "Restricting to:", str(restrictdatasets)
    print "Excluding:", str(nodatasets)
    if recursive:
        command = 'zfs snapshot -r %s' % fullsnapname
    else:
        command = 'zfs snapshot %s' % fullsnapname
    #print "Exec '%s'" % command
    p = subprocess.Popen(command.split(' '))
    p.wait()
    if p.returncode:
        raise Exception("Error executing '%s': %d" % (command, p.returncode))
    # ... then prune away undesired datasets if necessary
    if restrictdatasets:
        # remove whatever is not required, under ours
        for ds in get_datasets():
            # do not remove /usr/foo if there is any wanted dataset starting with /usr
            if not filter(lambda x: ds.startswith(x), restrictdatasets):
                destroy_snapshot(snapname, ds, recursive=False)
    if nodatasets:
        # remove whatever is explicitly excluded
        for ds in get_datasets():
            if ds in nodatasets:
                destroy_snapshot(snapname, dataset=ds, recursive=True)

def get_snapshots(dataset=''):
    """Return the list of snapshots order by increasing timestamp"""
    # filter my tags
    return os.listdir(dataset + ZFS_DEFAULT_SNAPSHOT_DIR)

