# -*- encoding: utf-8 -*-
import json
import socket
import time

import logging

log = logging.getLogger(__name__)


def _send_event(tag, data):
    __salt__['event.send'](tag, data=data)
    return {
        'name': tag,
        'result': True,
        'changes': data,
        'comment': ''
    }


def begin_stage(name):
    return _send_event('ceph-salt/stage/begin', data={'desc': name})


def end_stage(name):
    return _send_event('ceph-salt/stage/end', data={'desc': name})


def begin_step(name):
    return _send_event('ceph-salt/step/begin', data={'desc': name})


def end_step(name):
    return _send_event('ceph-salt/step/end', data={'desc': name})


def ssh(host, cmd):
    return __salt__['cmd.run_all']("ssh -o StrictHostKeyChecking=no "
                                   "-o UserKnownHostsFile=/dev/null "
                                   "-o ConnectTimeout=30 "
                                   "-i /home/cephadm/.ssh/id_rsa "
                                   "cephadm@{} \"{}\"".format(host, cmd))

def sudo_rsync(src, dest):
    return __salt__['cmd.run_all']("sudo rsync --rsync-path='sudo rsync' "
                                   "-e 'ssh -o StrictHostKeyChecking=no "
                                   "-o UserKnownHostsFile=/dev/null "
                                   "-o ConnectTimeout=30 "
                                   "-i /home/cephadm/.ssh/id_rsa' "
                                   "{} {} ".format(src, dest))

def get_remote_grain(host, grain):
    """
    Reads remote host grain by accessing '/etc/salt/grains' file directly.
    """
    python_script = '''
import json
import salt.utils.data
import yaml
with open('/etc/salt/grains') as grains_file:
    grains = yaml.full_load(grains_file)
val = salt.utils.data.traverse_dict_and_list(grains, '{}')
print(json.dumps({{'local': val}}))
'''.format(grain)
    ret = __salt__['ceph_salt.ssh'](
                   host,
                   "sudo python3 - <<EOF\n{}\nEOF".format(python_script))
    if ret['retcode'] != 0:
        return None
    return json.loads(ret['stdout'])['local']


def probe_ntp(ahost):
    import ntplib
    conn = ntplib.NTPClient()
    try:
        conn.request(ahost, version=3)
        return 0
    except socket.gaierror:
        return 2
    except ntplib.NTPException:
        return 1
    except:
        return 3


def is_safety_disengaged():
    execution = __pillar__['ceph-salt'].get('execution', {})
    safety_disengage_time = execution.get('safety_disengage_time')
    if safety_disengage_time and safety_disengage_time + 60 > time.time():
        return True
    return False


def probe_dns(*hostnames):
    """
    given a list of hostnames, verify that all can be resolved to IP addresses
    """
    ret_status = True
    for hostname in hostnames:
        log_msg = "probe_dns: attempting to resolve minion hostname ->{}<-".format(hostname)
        log.info(log_msg)
        try:
            socket.gethostbyname(hostname)
        except Exception as exc:
            log.error(exc)
            ret_status = False
        if not ret_status:
            break
    return ret_status


def probe_time_sync():
    units = [
        'chrony.service',  # 18.04 (at least)
        'chronyd.service', # el / opensuse
        'systemd-timesyncd.service',
        'ntpd.service', # el7 (at least)
        'ntp.service',  # 18.04 (at least)
    ]
    if not _check_units(units):
        log_msg = ('No time sync service is running; checked for: '
                   .format(', '.join(units)))
        log.warning(log_msg)
        return False
    return True


def _check_units(units):
    for unit in units:
        (enabled, installed, state) = __check_unit(unit)
        if enabled and state == 'running':
            log.info('Unit %s is enabled and running' % unit)
            return True
    return False


def __check_unit(unit_name):
    # NOTE: we ignore the exit code here because systemctl outputs
    # various exit codes based on the state of the service, but the
    # string result is more explicit (and sufficient).
    enabled = False
    installed = False
    cmd_ret = __salt__['cmd.run_all']("systemctl is-enabled {}".format(unit_name))
    if cmd_ret['retcode'] == 0:
        enabled = True
        installed = True
    elif cmd_ret['stdout'] and "disabled" in cmd_ret['stdout']:
        installed = True
    state = 'unknown'
    cmd_ret = __salt__['cmd.run_all']("systemctl is-active {}".format(unit_name))
    out = cmd_ret.get('stdout', '').strip()
    if out in ['active']:
        state = 'running'
    elif out in ['inactive']:
        state = 'stopped'
    elif out in ['failed', 'auto-restart']:
        state = 'error'
    return (enabled, installed, state)
