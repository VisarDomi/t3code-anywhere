"""Run the real shell policy with fake OS commands; no network state is changed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'macos/home-network'

class HomeNetworkTests(unittest.TestCase):
    def run_policy(self, *, wifi_ping=True, routed=False, mac='aa:bb:cc:dd:ee:ff', manual=True, age=60, watch=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); commands=root/'bin';commands.mkdir()
            conf=root/'config';miss=root/'miss';log=root/'calls'
            conf.write_text('ROUTER=192.168.1.1\nROUTER_MAC=aa:bb:cc:dd:ee:ff\nT3_LAN=no\nSERVICE=Wi-Fi\nIFACE=en4\nHOME_IP=192.168.1.199\n')
            miss.write_text(str(int(__import__('time').time())-age))
            source=SCRIPT.read_text().replace('conf=/usr/local/etc/home-network.conf',f'conf={conf}').replace('MISS=/var/run/home-network.miss',f'MISS={miss}')
            test_script=root/'policy';test_script.write_text(source)
            command='''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
if name=='ping': sys.exit(0 if '-b' not in args or os.environ['WIFI_PING']=='1' else 1)
if name=='arp': print('? (192.168.1.1) at '+os.environ['GATEWAY_MAC']+' on en4 ifscope [ethernet]')
if name=='ifconfig': print('status: active')
if name=='route': print('interface: en4\\nflags: <UP,'+('GATEWAY' if os.environ['ROUTED']=='1' else 'HOST,LLINFO')+'>')
if name=='networksetup':
 if args[0]=='-getinfo': print('Manual Configuration' if os.environ['MANUAL']=='1' else 'DHCP Configuration')
 else:
  with open(os.environ['CALLS'],'a') as f: f.write(json.dumps(args)+'\\n')
'''
            for name in ['ping','arp','ifconfig','route','networksetup','logger']:
                p=commands/name;p.write_text(command);p.chmod(0o755)
            notify=commands/'notifyutil';notify.write_text('#!/bin/sh\necho change\nsleep 0.2\necho change\n');notify.chmod(0o755)
            env=dict(os.environ,PATH=str(commands)+os.pathsep+os.environ['PATH'],
                     WIFI_PING='1' if wifi_ping else '0',ROUTED='1' if routed else '0',
                     GATEWAY_MAC=mac,MANUAL='1' if manual else '0',CALLS=str(log))
            if watch:
                result=subprocess.run(['/bin/bash',str(test_script),'--watch'],env=env,capture_output=True,timeout=20)
                self.assertEqual(result.returncode,1)  # notifyutil ended: launchd restarts the job
            else:
                subprocess.run(['/bin/sh',str(test_script)],env=env,check=True,capture_output=True,timeout=8)
            return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def away_rules(self, extra='', anchor='t3code-lan'):
        """The packet-filter rules written to an anchor away from home, with pfctl replaced by a recorder."""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); commands=root/'bin';commands.mkdir()
            conf=root/'config';rules=root/'rules'
            conf.write_text('ROUTER=192.168.1.1\nROUTER_MAC=aa:bb:cc:dd:ee:ff\nT3_LAN=yes\n'+extra)
            (commands/'pfctl').write_text('#!/bin/sh\nname=; prev=; for a in "$@"; do [ "$prev" = -a ] && name=${a##*.}; prev=$a; done\n'
                                          'case "$*" in *"-f -"*) cat > "$RULES.$name";; *"-s info"*) echo "Status: Enabled";; esac\n')
            (commands/'ping').write_text('#!/bin/sh\nexit 1\n')
            (commands/'logger').write_text('#!/bin/sh\n')
            for command in commands.iterdir(): command.chmod(0o755)
            script=root/'policy';script.write_text(SCRIPT.read_text().replace('conf=/usr/local/etc/home-network.conf',f'conf={conf}'))
            subprocess.run(['/bin/sh',str(script)],env=dict(os.environ,PATH=str(commands)+os.pathsep+os.environ['PATH'],RULES=str(rules)),
                           check=True,capture_output=True,timeout=8)
            loaded = Path(f'{rules}.{anchor}')
            return loaded.read_text().splitlines() if loaded.exists() else None

    def test_away_from_home_only_loopback_and_the_tailnet_reach_t3(self):
        rules=self.away_rules()
        self.assertEqual(len(rules),3)
        self.assertIn('100.64.0.0/10',rules[1])
        self.assertTrue(rules[2].startswith('block drop in quick'))

    def test_a_mac_without_tailscale_passes_only_loopback(self):
        rules=self.away_rules('TAILNET=no\n')
        self.assertEqual(rules,['pass in quick on lo0 proto tcp to any port 3773:3799',
                                'block drop in quick proto tcp to any port 3773:3799'])

    def test_tailnet_no_keeps_t3_off_tailscale_both_ways(self):
        self.assertEqual(self.away_rules('TAILNET=no\n', anchor='t3code-tailnet'),
                         ['block return in quick proto tcp from { 100.64.0.0/10, fd7a:115c:a1e0::/48 } to any port 3773:3799',
                          'block return out quick proto tcp from any to { 100.64.0.0/10, fd7a:115c:a1e0::/48 } port 3773:3799'])
        self.assertIsNone(self.away_rules(anchor='t3code-tailnet'))  # T3 over Tailscale stays allowed by default

    def test_live_home_gateway_keeps_fixed_address(self):
        self.assertEqual(self.run_policy(),[])

    def test_stale_arp_after_wifi_move_does_not_preserve_wrong_fixed_address(self):
        self.assertEqual(self.run_policy(wifi_ping=False),[['-setdhcp','Wi-Fi']])

    def test_old_router_reachable_through_nat_is_not_the_direct_home_lan(self):
        self.assertEqual(self.run_policy(routed=True,manual=False),[])

    def test_foreign_router_with_same_ip_uses_dhcp(self):
        self.assertEqual(self.run_policy(mac='11:22:33:44:55:66'),[['-setdhcp','Wi-Fi']])

    def test_short_wifi_interrupt_does_not_change_address_mode(self):
        self.assertEqual(self.run_policy(wifi_ping=False,age=0),[])

    def test_return_to_direct_home_lan_restores_fixed_address(self):
        self.assertEqual(self.run_policy(manual=False),[['-setmanualwithdhcprouter','Wi-Fi','192.168.1.199']])

    def test_watch_evaluates_at_start_and_once_per_burst_of_network_changes(self):
        restore=['-setmanualwithdhcprouter','Wi-Fi','192.168.1.199']
        self.assertEqual(self.run_policy(manual=False,watch=True),[restore,restore])

if __name__=='__main__':unittest.main()
