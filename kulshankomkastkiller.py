
"""kulshankomkastkiller.py

Install this script to /home/pi/bin and update the settings in main()
as necessary.

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
handler = RotatingFileHandler("/var/log/komkastkiller.log", maxBytes=10000, backupCount=10)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)


def can_ping(ip_address, interface):
    return subprocess.call(["ping", "-c", "1", "-W", "5", "-I", interface, ip_address], stdout=DEVNULL, stderr=DEVNULL) == 0


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

    def __init__(self, *hosts_to_ping, local_interface):
        self._hosts_to_ping = hosts_to_ping
        self._interface = local_interface
        self._up_since = None
        self._down_since = None
        
    def is_up(self):
        ping_results = [can_ping(ip, self._interface) for ip in self._hosts_to_ping]
        internet_up = any(ping_results)

        if not(internet_up):
            self._up_since = None
            self._down_since = datetime.now()
        elif self._up_since is None:
            self._up_since = datetime.now()
            self._down_since = None

        return self._up_since is not None


class RaspberryPi:

    RELAY_GPIO = 17

    def __init__(self, modem):
        self._relay_output = io.OutputDevice(self.RELAY_GPIO, initial_value=False, active_high=True)
        self._modem = modem
    
    def power_cycle_modem(self):
        def _sleep(dt):
            time.sleep(dt.seconds)
        self._modem.notify_reboot()
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
        self._modem = modem_monitor
        self._internet = internet_monitor
        self._pi = raspberry_pi
    
    def run(self):

        log.info("Starting.")
        
        while self._state != MonitoringStateMachine.HALT:
            time.sleep(1)

            if self._state == MonitoringStateMachine.MONITORING_MODEM:
                if self._modem.is_currently_booting():
                    log.info("Modem was recently rebooted... waiting.")
                else:

                    if self._modem.is_responsive():
                        self._state = MonitoringStateMachine.MONITORING_INTERNET
                        log.info("Modem is responsive, going to monitor internet.")
                    else:
                        log.warning("Modem unresponsive!")

            if self._state == MonitoringStateMachine.MONITORING_INTERNET:
                if self._internet.is_up():
                    log.info("Internet is up.")
                else:
                    self._state = MonitoringStateMachine.REBOOT_MODEM
                    log.warning("Internet down... rebooting modem.")

            if self._state == MonitoringStateMachine.REBOOT_MODEM:
                log.info("About to remove power...")
                self._pi.power_cycle_modem()
                log.info("Power has been restored.")
                self._state = MonitoringStateMachine.MONITORING_MODEM


            # HOLD: need to add protection for doing too many power cycles
            # per time. Need to add logic to back off, or just do maximum
            # of 1 cycle per hour or whatever.

            # HOLD: implement HALT state to close gracefully.

            # HOLD: Configuration file


            
def main():
    ethernet_interface = "eth0"
    modem = Modem(local_interface="lo", lan_ip="0.0.0.0", minimum_power_off_duration=timedelta(seconds=5), boot_duration=timedelta(seconds=20))
    internet = InternetMonitor("8.8.8.8", "1.1.1.1", local_interface=ethernet_interface)
    pi = RaspberryPi(modem)

    state_machine = MonitoringStateMachine(modem, internet, pi)
    state_machine.run()

    

if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        log.critical(f"Unexpected {err}, {type(err)}")
        log.critical(traceback.format_exc())
        raise
