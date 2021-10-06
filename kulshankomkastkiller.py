
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


logger = logging.getLogger('KomKastKiller')
logger.setLevel(logging.INFO)
handler = RotatingFileHandler("/var/log/komkastkiller.log", maxBytes=10000, backupCount=10)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


def can_ping(ip_address):
    return subprocess.call(["ping", "-c", "1", ip_address], stdout=DEVNULL, stderr=DEVNULL) == 0


class Modem:

    def __init__(self, lan_ip, minimum_power_off_duration, boot_duration):
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
        alive = can_ping(self._lan_ip)
        if not(alive):
            self._up_since = None
            self._down_since = datetime.now()
        elif self._up_since is None:
            self._up_since = datetime.now()
            self._down_since = None
        return self._up_since is not None

    
class InternetMonitor:

    def __init__(self, *hosts_to_ping):
        self._hosts_to_ping = hosts_to_ping
        self._up_since = None
        self._down_since = None
        
    def is_up(self):
        ping_results = [can_ping(ip) for ip in self._hosts_to_ping]
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

        logger.info("Starting.")
        
        while self._state != MonitoringStateMachine.HALT:
            time.sleep(1)

            if self._state == MonitoringStateMachine.MONITORING_MODEM:
                if self._modem.is_currently_booting():
                    logger.info("Modem was recently rebooted... waiting.")
                else:

                    if self._modem.is_responsive():
                        self._state = MonitoringStateMachine.MONITORING_INTERNET
                        logger.info("Modem is responsive, going to monitor internet.")
                    else:
                        logger.warning("Modem unresponsive!")

            if self._state == MonitoringStateMachine.MONITORING_INTERNET:
                if self._internet.is_up():
                    logger.info("Internet is up.")
                else:
                    self._state = MonitoringStateMachine.REBOOT_MODEM
                    logger.warning("Internet down... rebooting modem.")

            if self._state == MonitoringStateMachine.REBOOT_MODEM:
                logger.info("About to remove power...")
                self._pi.power_cycle_modem()
                logger.info("Power has been restored.")
                self._state = MonitoringStateMachine.MONITORING_MODEM


            # HOLD: Syslog logging
            
            # HOLD: need to add protection for doing too many power cycles
            # per time. Need to add logic to back off, or just do maximum
            # of 1 cycle per hour or whatever.

            # HOLD: Init scripts to start and stop this script as a service
            #       (also will need to implement HALT state)

            # HOLD: Configuration file?


            
def main():
    modem = Modem(lan_ip="0.0.0.0", minimum_power_off_duration=timedelta(seconds=1), boot_duration=timedelta(seconds=10))
    internet = InternetMonitor("google.com", "75.75.75.75")
    pi = RaspberryPi(modem)

    state_machine = MonitoringStateMachine(modem, internet, pi)
    state_machine.run()

    

if __name__ == "__main__":
    main()
    
