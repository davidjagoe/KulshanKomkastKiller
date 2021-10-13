
"""kulshankomkastkiller.py

Copyright 2021 David Jagoe.

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.


Hardware:

  - This software runs on a RaspberryPi. Only models 3B and 4B have
    been tested. You will additionally need to provide an appropriate
    relay. HOLD for further BOM documentation.


Installation instructions:

  - Install this script to /home/pi/bin and update the settings in
    main() as necessary.

  - Install the accompanying komkastkiller.service to
    /lib/systemd/system/kkiller.service and enable the service using
    the command: 'sudo systemctl enable kkiller.service'.

"""


import logging
import os
import subprocess
import time

from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from subprocess import DEVNULL


try:
    import gpiozero as io
except ImportError:
    import fakeio as io


log = logging.getLogger('KomKastKiller')
log.setLevel(logging.INFO)
try:
    handler = RotatingFileHandler("/var/log/komkastkiller.log", maxBytes=1000000, backupCount=10)
except PermissionError:
    handler = RotatingFileHandler("/tmp/komkastkiller.log", maxBytes=10000, backupCount=10)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)


def can_ping(ip_address, interface):
    return subprocess.call(["ping", "-c", "1", "-W", "10", "-I", interface, ip_address], stdout=DEVNULL, stderr=DEVNULL) == 0


def can_curl(host, interface, max_time="10"):
    # Note, ideally we would include the "--dns-interface eth0" option
    # but that option does not exist on the libcurl provided on
    # raspberry-pi os.
    return subprocess.call(["curl", "--interface", interface, "--max-time", max_time, "--head", host], stdout=DEVNULL, stderr=DEVNULL) == 0


class Modem:

    def __init__(self, local_interface, lan_ip, minimum_power_off_duration, boot_duration):
        self._interface = local_interface
        self._lan_ip = lan_ip
        self._power_off_duration = minimum_power_off_duration
        self._boot_duration = boot_duration
        self._up_since = None
        self._down_since = None
        self._last_reboot = datetime.now()

    def notify_reboot(self):
        self._up_since = None
        self._down_since = datetime.now()
        self._last_reboot = datetime.now()
        
    def get_power_off_duration(self):
        return self._power_off_duration
        
    def is_currently_booting(self):
        return (datetime.now() - self._last_reboot) < self._boot_duration

    def is_responsive(self):
        alive = can_ping(self._lan_ip, self._interface)
        if not(alive):
            self._up_since = None
            self._down_since = datetime.now()
        elif self._up_since is None:
            self._up_since = datetime.now()
            self._down_since = None
        return self._up_since is not None


class InternetMonitor:

    def __init__(self, *remote_hosts, local_interface, acceptable_no_comms_seconds, curl_max_time):
        self._remote_hosts = remote_hosts
        self._interface = local_interface
        self._acceptable_no_comms_seconds = acceptable_no_comms_seconds
        self._curl_max_time = str(curl_max_time)
        self._last_curl = datetime.now()
        self._up_since = None
        self._down_since = None
        
    def notify_reboot(self):
        self._last_curl = datetime.now()

    def is_up(self):
        now = datetime.now()
        curl_results = [can_curl(host, self._interface, self._curl_max_time) for host in self._remote_hosts]
        good_curl = any(curl_results)

        if good_curl:
            self._last_curl = datetime.now()

        time_since_last_curl = now - self._last_curl
            
        if not(good_curl) and (time_since_last_curl.seconds > self._acceptable_no_comms_seconds):
            self._up_since = None
            self._down_since = datetime.now()
        elif self._up_since is None:
            self._up_since = datetime.now()
            self._down_since = None

        return self._up_since is not None


class RaspberryPi:

    RELAY_GPIO = 17

    def __init__(self, modem, internet_monitor):
        self._relay_output = io.OutputDevice(self.RELAY_GPIO, initial_value=False, active_high=True)
        self._modem = modem
        self._internet_monitor = internet_monitor
    
    def power_cycle_modem(self):
        def _sleep(dt):
            time.sleep(dt.seconds)
        self._modem.notify_reboot()
        self._internet_monitor.notify_reboot()
        self._relay_output.on()
        _sleep(self._modem.get_power_off_duration())
        self._relay_output.off()

        
class MonitoringStateMachine:

    # STATES
    MONITORING_MODEM = "monitoring_modem"
    MONITORING_INTERNET = "monitoring_internet"
    REBOOT_MODEM = "reboot_modem"
    HALT = "halt"

    def __init__(self, modem_monitor, internet_monitor, raspberry_pi):
        self._state = MonitoringStateMachine.MONITORING_MODEM
        self._prev_state = None
        self._modem = modem_monitor
        self._internet = internet_monitor
        self._pi = raspberry_pi
    
    def run(self):

        log.info("Starting.")
        
        while self._state != MonitoringStateMachine.HALT:
            time.sleep(1)
            if self._state != self._prev_state:
                log.info("Entered state <{0}>".format(self._state))
                self._prev_state = self._state

            if self._state == MonitoringStateMachine.MONITORING_MODEM:
                if self._modem.is_currently_booting():
                    log.debug("Modem was recently rebooted... waiting.")
                else:

                    if self._modem.is_responsive():
                        self._state = MonitoringStateMachine.MONITORING_INTERNET
                        log.debug("Modem is responsive, going to monitor internet.")
                    else:
                        log.warning("Modem unresponsive!")

            elif self._state == MonitoringStateMachine.MONITORING_INTERNET:
                if self._internet.is_up():
                    log.debug("Internet is up.")
                else:
                    self._state = MonitoringStateMachine.REBOOT_MODEM
                    log.debug("Internet down... rebooting modem.")

            elif self._state == MonitoringStateMachine.REBOOT_MODEM:
                log.debug("About to remove power...")
                self._pi.power_cycle_modem()
                log.debug("Power has been restored.")
                self._state = MonitoringStateMachine.MONITORING_MODEM


            # HOLD: need to add protection for doing too many power cycles
            # per time. Need to add logic to back off, or just do maximum
            # of 1 cycle per hour or whatever.

            # HOLD: implement HALT state to close gracefully.

            # HOLD: Configuration file


            
def main():
    # Note: change 'lo' below to 'eth0' before using in production.
    modem = Modem(local_interface="lo", lan_ip="0.0.0.0", minimum_power_off_duration=timedelta(seconds=5), boot_duration=timedelta(seconds=120))
    internet = InternetMonitor("google.com", "facebook.com", local_interface="eth0", acceptable_no_comms_seconds=60, curl_max_time=5)
    pi = RaspberryPi(modem, internet)

    state_machine = MonitoringStateMachine(modem, internet, pi)
    state_machine.run()

    

if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        log.critical(f"Unexpected {err}, {type(err)}")
        log.critical(traceback.format_exc())
        raise
