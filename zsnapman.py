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

import sys
import os, subprocess
import calendar
from datetime import datetime, timedelta

import sys
from optparse import OptionParser

import zfs

### Primary settings

# which datasets to exclude from backups
exclude_datasets = [
        '/nobackup',
        '/usr/ports',
        '/usr/src'
        ]


# name of the zpool to take snapshots from
DEFAULT_ZPOOL = 'zroot'

# how many snapshots to keep, or None for no limit (see SNAPS_BACKLOG_MAXDAYS)
SNAPS_BACKLOG_NUMBER=None

# remove snapshots older than this many days.
SNAPS_BACKLOG_MAXDAYS=45


### Secondary settings

# use this tag for snapshots by default
DEFAULT_SNAP_CONTEXT = 'default'

# each snapshot name begins with this part
DEFAULT_SNAP_PREFIX = 'zbk'

# how timestamp is represented in the snapshot name (as in python time format)
DEFAULT_TIMESTRFORMAT = '%d_%m_%Y__%H_%M_%S'


### OPTION PARSING
class SnapshotContext:
    def __init__(self, tag=DEFAULT_SNAP_CONTEXT):
        """Construct a snapshot context based on a given name."""
        self.tag = tag

    ### SNAPSHOT NAME
    def _snaptimestr_to_timestamp(self, snaptimestr):
        """Return the datetime object of a snapshot from its date tag"""
        return datetime.strptime(snaptimestr, DEFAULT_TIMESTRFORMAT)

    def _timestamp_to_snaptimestr(self, timestamp):
        """Return the snapshot time string from a datetime timestamp"""
        return timestamp.strftime(DEFAULT_TIMESTRFORMAT)

    def _get_snapname_time(self, snapname):
        """Return the human-readable timestamp contained in a snapshot name"""
        return snapname.split('-')[2]

    def _get_snap_time(self, snapname):
        """Return the datetime for a snapshot"""
        return self._snaptimestr_to_timestamp(self._get_snapname_time(snapname))

    def make_snap_name(self, timestamp=None):
        """Create a well-formatted snapshot name for this context.

        The snapshot name will contain a time tag reflecting the given value, or now if None is given."""
        if not timestamp:
            timestamp = datetime.now()
        return "%s-%s-%s" % (DEFAULT_SNAP_PREFIX, self.tag, self._timestamp_to_snaptimestr(timestamp))
    
    def get_snapshots(self, dataset=''):
        """Return snapshots belonging to this context."""
        # get all snapshots
        allsnaps = zfs.get_snapshots(dataset)
        # sort out those in my context
        my_snapshots = filter(lambda x: x.startswith('%s-%s-' % (DEFAULT_SNAP_PREFIX, self.tag)), allsnaps)
        # sort them oldest to newest
        return sorted(my_snapshots, key=lambda x: self._get_snap_time(x))

    def get_fresh_snapshots(self, backlog_num=None, backlog_minutes=None, dataset=''):
        """Return the list of snapshots fresh wrt an age or a sequence size."""
        all_snaps = self.get_snapshots(dataset)
        if backlog_num is not None:
            # remove the exceeding oldest
            all_snaps = all_snaps[-backlog_num:]
        if backlog_minutes is not None:
            timelimit = datetime.now() - timedelta(minutes=backlog_minutes)
            all_snaps = filter(lambda x: self._get_snap_time(x) > timelimit, all_snaps)
        return all_snaps

    def get_outdated_snapshots(self, backlog_num=None, backlog_minutes=None, dataset=''):
        """Return the list of snapshots outdated wrt an age or a sequence size."""
        return filter(lambda x: x not in self.get_fresh_snapshots(backlog_num, backlog_minutes, dataset=dataset), self.get_snapshots(dataset))
        

def is_snapman_snapshot(snapname):
    """Return whether a snapshot name is managed by this tool."""
    return snapname.startswith(DEFAULT_SNAP_PREFIX + '-')

def existing_contexts(dataset=''):
    """Return the set of existing contexts found on the system"""
    return set([x.split('-')[1] for x in zfs.get_snapshots(dataset) if is_snapman_snapshot(x)])


if __name__ == '__main__':
    # print current snaps
    if len(sys.argv) > 1:
        tag = sys.argv[1]
    else:
        tag = DEFAULT_SNAP_TAG
    cursnaps = get_snaps(tag)
    print "Current snaps:"
    if cursnaps:
        print '\n'.join(cursnaps)
    else:
        print "None"
    # take new snap
    newsnapname = make_snap_name(tag=tag)
    take_snapshot(newsnapname, nodatasets=exclude_datasets)
    # remove stale snaps
    all_snaps = get_snaps()
    # exceeding backlog number
    if SNAPS_BACKLOG_NUMBER:
        print "Looking for snapshots exceeding backlog (%d) ..." % SNAPS_BACKLOG_NUMBER
        while len(all_snaps) > SNAPS_BACKLOG_NUMBER:
            destroy_snapshot(all_snaps[0])
            all_snaps.remove(0)
        print "Done."
    # exceeding backlog age
    if SNAPS_BACKLOG_MAXDAYS:
        timelimit = datetime.now() - timedelta(days=SNAPS_BACKLOG_MAXDAYS)
        print "Looking for snapshots before %s ..." % str(timelimit)
        while len(all_snaps) > 0:
            snaptime = snaptimestr_to_timestamp(get_snapname_time(all_snaps[0]))
            if snaptime >= timelimit:
                break
            destroy_snapshot(all_snaps[0])
            all_snaps.remove(0)
        print "Done."
