
class OutputDevice:

    def __init__(self, pin, *args, active_high=True, initial_value=False, **kwargs):
        self._pin = pin
        self._active_high = active_high
        self._value = initial_value

    def on(self):
        self._value = True

    def off(self):
        self._value = False

    def toggle(self):
        self._value = not(self._value)

    @property
    def active_high(self):
        return self._active_high

    @property
    def value(self):
        return self._value
