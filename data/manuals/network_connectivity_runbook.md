---
device_model: all
---
# Network Connectivity Runbook (POS, ATM and Kiosk)

Synthetic sample runbook for demonstration purposes. Applies to all device models.

## Quick checks
1. Check the link light on the device and on the switch port. No light means a cable or port fault.
2. Replace the patch cable with a known good one and try another switch port.
3. Open the diagnostics menu and confirm the device has an IP address. An address starting with 169.254 means DHCP failed.

## Connectivity tests
1. Ping the default gateway. If it fails, the problem is local (cable, switch, VLAN).
2. Ping the payment or back-end host by IP address. If this works but the name does not resolve, the problem is DNS.
3. Check the firewall rules for the payment port. A blocked port causes host timeouts (P-2002, A-5001, K-4002) even when ping works.

## Restarting the network service
From the service menu choose Network > Restart service. If the device does not recover in two minutes, reboot the device. Never reboot an ATM while a cash operation is in progress.

## Wireless kiosks
Check the Wi-Fi signal strength in the diagnostics menu. Below -70 dBm the connection is unreliable, so move the access point closer or add one.

## Escalation
Escalate to the network team if several devices at the same site lose connectivity at once. This usually points to the site router or the WAN link and not to the device.
