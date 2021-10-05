
from datetime import datetime


# States
MONITORING_MODEM = "start"
MONITORING_INTERNET = "monitoring_internet"
REBOOT_MODEM = "reboot_modem"
HALT = "halt"



def create_initial_state():
    return {"CONFIG":
            {"modem_lan_ip": "10.1.10.1",
             "hosts": ["google.com"],
             "power_off_duration": datetime.timedelta(seconds=10),
             "modem_boot_duration": datetime.timedelta(minutes=2),
             "relay_pin": -1,
             },
            "STATE": MONITORING_MODEM,
            "MODEM": {"up_since": None, "down_since": None, "last_reboot": datetime.now()},
            "INTERNET": {"up_since": None, "down_since": None},
            
            }


def get_state(S):
    return S["STATE"]


def recently_rebooted(S):
    now = datetime.now()
    delta = now - S["MODEM"]["last_reboot"]
    return delta < S["CONFIG"]["modem_boot_duration"]


def modem_responsive(S):
    return S["MODEM"]["up_since"] is not None


def silence_sirens(S):
    pass


def start_modem_siren(S):
    pass


def start_reboot_siren(S):
    pass


def power_cycle_modem(S):
    # Open relay
    time.sleep(S["CONFIG"]["power_off_duration"])
    # Close relay


def can_ping(ip_address):
    pass


def do_record_internet_status(S):
    hosts = S.get("CONFIG", {}).get("hosts", [])

    ping_results = [can_ping(ip) for ip in hosts]
    internet_up = any(ping_results)

    internet_state = S["INTERNET"]
    if not(internet_up):
        internet_state["up_since"] = None
        internet_state["down_since"] = datetime.now()
    elif internet_state["up_since"] is None:
        internet_state["up_since"] = datetime.now()
        internet_state["down_since"] = None

    return S
    


def do_record_modem_responsiveness(S):
    modem_ip = S.get("CONFIG", {}).get("modem_lan_ip", "0.0.0.0")
    alive = can_ping(modem_ip)
    modem_state = S["MODEM"]
    if not(alive):
        modem_state["up_since"] = None
        modem_state["down_since"] = datetime.now()
    elif modem_state["up_since"] is None:
        modem_state["up_since"] = datetime.now()
        modem_state["down_since"] = None

    return S


def main():

    S = create_initial_state()

    while get_state(S) != HALT:

        if get_state(S) == MONITORING_MODEM:
            if recently_rebooted(S):
                pass
            else:

                S = do_record_modem_responsiveness(S)
                if modem_responsive(S):
                    silence_sirens(S)
                    S["STATE"] = MONITORING_INTERNET
                else:
                    start_modem_siren(S)

        if get_state(S) == MONITORING_INTERNET:
            S = do_record_internet_status(S)
            if internet_up(S):
                silence_sirens(S)
            else:
                S["STATE"] = REBOOT_MODEM
            
        if get_state(S) == REBOOT_MODEM:
            start_reboot_siren(S)
            power_cycle_modem(S)
            S["STATE"] = MONITORING_MODEM


        # HOLD: need to add protection for doing too many power cycles
        # per time. Need to add logic to back off, or just do maximum
        # of 1 cycle per hour or whatever.
            
                

if __name__ == "__main__":
    main()
    
