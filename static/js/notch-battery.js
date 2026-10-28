// Battery alerts for the notch. Quiet by design: it speaks when the charger is connected, when the battery is full,
// and when charge runs low (once at 20%, once at 10%). It never announces what was already true when Relay started.
export const LOW = 20;
export const VERY_LOW = 10;

export function createBatteryWatcher({ announce, enabled = () => true }) {
  let previous = null;
  let warned = 0; // the lowest warning already given since the last charge: 0, LOW or VERY_LOW

  return {
    update(reading) {
      if (!reading || !Number.isFinite(reading.percent)) {
        previous = null; // no battery, or no reading: start fresh when one comes back
        return;
      }
      const before = previous;
      previous = reading;
      if (reading.plugged || reading.percent > LOW + 5) warned = 0; // charged up again: warn once more next time
      const level = reading.plugged ? 0 : reading.percent <= VERY_LOW ? VERY_LOW : reading.percent <= LOW ? LOW : 0;
      let message = null;
      if (level && (warned === 0 || level < warned)) {
        warned = level;
        if (before) {
          message = level === VERY_LOW
            ? { kind: 'lowbattery', title: 'Battery very low', detail: `${reading.percent}% left · plug in now` }
            : { kind: 'lowbattery', title: 'Battery low', detail: `${reading.percent}% left · plug in the charger` };
        }
      }
      if (before && reading.plugged && !before.plugged) {
        message = { kind: 'charging', title: 'Charger connected', detail: reading.charged ? `${reading.percent}% · charged` : `${reading.percent}% · charging` };
      } else if (before && reading.plugged && reading.charged && !before.charged) {
        message = { kind: 'charging', title: 'Battery is full', detail: 'You can unplug the charger' };
      }
      if (message && enabled()) announce(message);
    }
  };
}
