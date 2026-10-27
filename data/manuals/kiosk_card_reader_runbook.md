---
device_model: HX-KIOSK-300
---
# HX-KIOSK-300 Card Reader Troubleshooting

Synthetic sample runbook for demonstration purposes.

## Reader not detected (K-1001)
1. Exit the kiosk application using the service key combination and open the Service Menu.
2. Open Peripherals and check whether the card reader is listed. If it is not, power the kiosk off.
3. Reseat the USB cable at both the reader and the kiosk board. Prefer the rear USB ports.
4. Power on and open Peripherals again. If the reader appears, run the reader self test.
5. If the reader is still missing, swap the cable. If it still fails, replace the reader and record the serial number.

## Read errors (K-1002)
Insert a cleaning card three times, then run the self test. Inspect the slot for debris or a foreign object. Repeated read errors on a single card type usually indicate a worn reader head.

## Card capture bin full (K-1003)
Open the cabinet with the service key, empty the capture bin, log the card numbers masked to the last four digits, and reset the counter under Service Menu > Counters.

## Touchscreen problems (K-3001)
Clean the screen, restart the display service, and recalibrate the touch panel from Service Menu > Display > Calibrate. If touches are offset after calibration, check the screen for cracks and replace the panel.
