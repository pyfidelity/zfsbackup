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


import subprocess
import time
import signal
import os
import sys
from datetime import datetime
from optparse import OptionParser


import zfs
import zsnapman

DEFAULT_ZBK_TAG = 'zbk'


### UTILITY FUNCTIONS

# options
global _opts


def _make_backup_filename(seqno, tag=None, dataset=None, path='.', include_hostname=True, suffix=''):
    """Return a suitable backup filename for a given seqno.

    If dataset is None, the root is assumed."""
    global _opts
    if not dataset:
        dataset = zfs.get_default_pool()
    else:
        # translate bad characters to _
        dataset = dataset.replace('/', '_')
    if not tag:
        if _opts: tag=_opts.context
        else: tag=DEFAULT_ZBK_TAG
    if path == '.' and _opts: path=_opts.output.rstrip('/')
    return '%s/backup-%s-%s-%d-%s-%s.zfsdump%s' % (path, os.uname()[1].replace('-', '_').replace('.', '_'), tag, seqno, datetime.now().strftime(zsnapman.DEFAULT_TIMESTRFORMAT), dataset, suffix)


def _run_command(commandstr, outfile, compress=False):
    """Run command saving stdout into outfile"""
    if compress:
        mycommand = '%s | gzip -2 > %s' % (commandstr, outfile)
    else:
        mycommand = '%s > %s' % (commandstr, outfile)
    print "Exec '%s'" % (mycommand)
    pstart = time.time()
    p = subprocess.Popen(mycommand, shell=True)
    try:
        sts = os.waitpid(p.pid, 0)[1]
    except:
        # kill the child if I'm interrupted here
        os.kill(p.pid, signal.SIGTERM)
    if p.returncode:
        raise Exception("Error executing '%s': %d" % (mycommand, p.returncode))
    print "Run time: %.1f sec" % (time.time() - pstart)


### FULL AND INCREMENTAL BACKUP LOGIC
def full_send(snapname, dataset=None, recursive=True, compress=False):
    """Perform a full dump of a snapshot"""
    global _opts

    print "Back up '%s'" % snapname
    if not compress:
        if _opts: compress=_opts.compress
    if compress: suffix = '.gz'
    else: suffix = ''
    bkfilename = _make_backup_filename(0, dataset=dataset, suffix=suffix)
    if not dataset: dataset = ''
    targetsnap = '%s%s@%s' % (zsnapman.DEFAULT_ZPOOL, dataset, snapname)
    if recursive:
        command = 'zfs send -R %s' % targetsnap
    else:
        command = 'zfs send %s' % targetsnap
    _run_command(command, bkfilename, compress)
    print "Done: full dump of snapshot '%s' into file %s" % (snapname, bkfilename)
    return bkfilename

def incremental_send(snapname_from, snapname_to, seqno, dataset=None, recursive=True, compress=False):
    """Perform an incremental dump between two snapshots"""

    global _opts
    print "Backing up from '%s' -> '%s' (seqno %d)" % (snapname_from, snapname_to, seqno)
    if not compress:
        if _opts: compress=_opts.compress
    if compress: suffix = '.gz'
    else: suffix = ''
    bkfilename = _make_backup_filename(seqno, dataset=dataset, suffix=suffix)
    if not dataset: dataset = ''
    targetsnap = '%s%s@%s' % (zsnapman.DEFAULT_ZPOOL, dataset, snapname_to)
    if recursive:
        command = 'zfs send -R -i @%s %s' % (snapname_from, targetsnap)
    else:
        command = 'zfs send -i @%s %s' % (snapname_from, targetsnap)
    _run_command(command, bkfilename, compress)
    print "Done: incremental dump '%s' -> '%s' into file %s" % (snapname_from, snapname_to, bkfilename)
    return bkfilename

def _handle_alternate_dumps(previous_snaps, current_snapname, individuals, backlog_num=None):
    """Dump according to an alternate scheme.

    Keep last backlog_num snaps, and dump with this algorithm:
        step 1) FULL      0
        step 2) INCR     0-1
        step 3) INCR     0-2
        step 4) INCR     1-3
        step 5) INCR     2-4
        ...
    If a backlog_num is specified, keep that many most-recent snapshots; if 0,
    infinite; if not specified, remove all but last."""
    num_previous_snaps = len(previous_snaps)
    if backlog_num and len(previous_snaps) >= backlog_num:
        # time to start from scratch
        print "Starting over after %d steps." % len(previous_snaps)
        for ds in individuals:
            bkfname = full_send(current_snapname, dataset=ds)
        # prune old serie, if any
        print "Cleaning up snapshots from old series."
        for snap in previous_snaps:
            zfs.destroy_snapshot(snap)
        _done()
    # go incremental from 2 steps ago
    assert num_previous_snaps > 0
    if num_previous_snaps == 1:
        # backup from base snap
        if not individuals:
            incremental_send(previous_snaps[0], current_snapname, num_previous_snaps)
        else:
            for ds in individuals:
                incremental_send(previous_snaps[0], current_snapname, num_previous_snaps, dataset=ds)
    else:
        # backup from 2 steps before
        if not individuals:
            incremental_send(previous_snaps[-2], current_snapname, num_previous_snaps)
        else:
            for ds in individuals:
                incremental_send(previous_snaps[-2], current_snapname, num_previous_snaps, dataset=ds)


def _handle_sequential_dumps(previous_snaps, current_snapname, individuals, backlog_num=None):
    """Dump according to a sequential scheme.

    Keep last backlog_num snaps, and dump with this algorithm:
        step 1) FULL         0
        step 2) INCR        0-1
        step 3) INCR        1-2
        ..
    If a backlog_num is specified, keep that many most-recent snapshots; if 0,
    infinite; if not specified, remove all but last."""
    global _opts
    if backlog_num is None and _opts: backlog_num=_opts.backlog_num
    num_previous_snaps = len(previous_snaps)
    if not individuals:
        incremental_send(previous_snaps[-1], current_snapname, num_previous_snaps)
    else:
        for ds in individuals:
            incremental_send(previous_snaps[-1], current_snapname, num_previous_snaps, dataset=ds)
    # clean up old serie
    if backlog_num == 0 or backlog_num > len(previous_snaps): return
    if backlog_num is None: backlog_num = 1
    for snap in previous_snaps[:len(previous_snaps)-backlog_num+1]:
        zfs.destroy_snapshot(snap)


def get_option_parser():
    opars = OptionParser()

    # snapshot handling
    opars.add_option('-c', '--context', dest='context', help='your label/group/type for this snapshot', default='default')
    opars.add_option('-l', '--list', action='store_true', dest='list_snapshots', help='list snapshots in the given context', default=False)
    opars.add_option('-n', '--no-snapshot', action='store_true', dest='nosnap', help="do not take snapshot, operate (and prune) with context's most recent one", default=False)
    opars.add_option('-b', '--backlog', type="int", dest='backlog_num', metavar='NUM', help='avoid self-management: keep this many most-recent snapshots of this tag (0 = infinite)', default=None)
    opars.add_option('-a', '--maxage', type="int", dest='maxminutes', metavar='MINUTES', help='remove snapshots of this tag older than this many minutes', default=None)
    opars.add_option('-x', '--exclude', action='append', dest='exclude_datasets', metavar='DS_MNTPOINT', help='exclude dataset from snapshot (omit zfspool name) [repeatable]', default=None)
    opars.add_option('-d', '--dataset', action='append', dest='only_datasets', metavar='DS_MNTPOINT', help="snapshot & send this daset (recursively), not all (overrides -i) [repeatable]", default=None)

    # dump options
    opars.add_option('-s', '--send', action='store_true', dest='send', help='dump/send snapshot after taking it (full or incremental as appropriate)', default=False)
    opars.add_option('-0', '--fulldump', action='store_true', dest='fulldump', help='perform a full dump regardless of availability of former snaps', default=False)
    opars.add_option('-i', '--dump-individually', action='append', dest='individual_dump_ds', metavar='DS_MNTPOINT', help='no root-recursion; dump this dataset individually [repeatable]', default=None)
    opars.add_option('-k', '--compress', action='store_true', dest='compress', help='compress (gzip -4) dumped files', default=False)
    # dump strategies
    opars.add_option('-t', '--alternate', action='store_true', dest='alternate_dumps', help='alternate dumps (0, 0-1, 0-2, 1-3, 2-4, 3-5, ..)', default=False)
    opars.add_option('-o', '--output', dest='output', metavar='DIR', help='dump backups into such directory rather than here', default='./')


    # manual snapshot handling options
    opars.add_option('--prune-exceeding', type='int', dest='prune_exceeding_minutes', metavar='MINUTES', help='destroy snapshots older than X minutes', default=None)

    return opars


def _done(res=0):
    print "Done."
    sys.exit(res)

def _list_context(context, dataset=''):
    # print snaps for all contexts
    global _opts
    print "* Context '%s':" % context
    print "** Fresh snapshots:"
    snapctx = zsnapman.SnapshotContext(context)
    for snap in snapctx.get_fresh_snapshots(backlog_num=_opts.backlog_num, backlog_minutes=_opts.maxminutes, dataset=dataset):
        print snap
    print "\n** Outdated snapshots:"
    for snap in snapctx.get_outdated_snapshots(backlog_num=_opts.backlog_num, backlog_minutes=_opts.maxminutes, dataset=dataset):
        print snap


### MAIN

def main():
    # get user options
    global _opts
    _opts, args = get_option_parser().parse_args()
    # cleanup options
    if _opts.exclude_datasets: _opts.exclude_datasets = [ds.rstrip('/') for ds in _opts.exclude_datasets]
    if _opts.only_datasets: _opts.only_datasets = [ds.rstrip('/') for ds in _opts.only_datasets]
    if _opts.individual_dump_ds: _opts.individual_dump_ds = [ds.rstrip('/') for ds in _opts.individual_dump_ds]
    # get context
    snapctx = zsnapman.SnapshotContext(_opts.context)

    if _opts.individual_dump_ds:
        # pick the first as representative
        operating_dataset = _opts.individual_dump_ds[0]
    else:
        # default to root
        operating_dataset = ''

    # some manual handling?
    if _opts.list_snapshots:
        if _opts.context == '*':
            print "Contexts available:"
            for c in zsnapman.existing_contexts(): print c
            for ctx in zsnapman.existing_contexts():
                _list_context(ctx, operating_dataset)
        else:
            _list_context(_opts.context, operating_dataset)
        _done()
    elif _opts.prune_exceeding_minutes is not None:
        print "Pruning '%s' snapshots older than '%d' minutes" % (_opts.context, _opts.prune_exceeding_minutes)
        for snap in snapctx.get_outdated_snapshots(backlog_minutes=_opts.prune_exceeding_minutes, dataset=operating_dataset):
            zfs.destroy_snapshot(snap)
        _done()

    ## done with manual handling

    # kill outdated snapshots
    for snap in snapctx.get_outdated_snapshots(backlog_num=_opts.backlog_num, backlog_minutes=_opts.maxminutes, dataset=operating_dataset):
        zfs.destroy_snapshot(snap)
    # get survived snaps in this context
    previous_snaps = snapctx.get_snapshots(dataset=operating_dataset)
    # take new snapshot
    # what dataset take individually?
    if _opts.only_datasets:
        ids = _opts.only_datasets
    elif _opts.individual_dump_ds:
        # these
        ids = _opts.individual_dump_ds
    else:
        # none specific, dump once root recursively
        ids = None
    # proceed taking the snapshot for the current session
    if not _opts.nosnap:
        current_snapname = snapctx.make_snap_name()
        zfs.take_snapshot(current_snapname, restrictdatasets=ids, nodatasets=_opts.exclude_datasets)
    else:
        if not previous_snaps:
            print "No existing snapshots in '%s'. Cannot proceed." % _opts.context
        current_snapname = previous_snaps.pop()

    if not _opts.send: _done()
    # dump is required
    if _opts.fulldump or len(previous_snaps) == 0 or (_opts.backlog_num is not None and len(previous_snaps) >= _opts.backlog_num):
        # full dump
        if not ids:
            bkfname = full_send(current_snapname)
        else:
            for ds in ids:
                bkfname = full_send(current_snapname, dataset=ds)
        _done()
    # look for what incremental algorithm the user wants
    if _opts.alternate_dumps:
        _handle_alternate_dumps(previous_snaps, current_snapname, individuals=ids)
    else:
        _handle_sequential_dumps(previous_snaps, current_snapname, individuals=ids)
    _done()


if __name__ == '__main__':
    main()
