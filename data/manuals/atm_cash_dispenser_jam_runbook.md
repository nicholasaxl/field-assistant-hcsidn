---
device_model: HX-ATM-500
---
# HX-ATM-500 Cash Dispenser Jam Runbook

Synthetic sample runbook for demonstration purposes.

## Safety and access
Cash handling requires two-person control. Never open the safe alone and never leave the vault door open unattended. Take the ATM out of service from the supervisor menu before opening any door.

## Clearing a note jam (A-1001)
1. Take the ATM out of service and open the front door, then the safe door, with a second authorized person present.
2. Remove the affected cassette and check the pick area for torn or folded notes.
3. Open the transport path cover and remove any notes. Use only the supplied tool, never a screwdriver or a blade.
4. Check the rollers for dust or residue and clean them with the approved cleaning cloth.
5. Reseat the cassette until it clicks and close the doors.
6. Run Supervisor Menu > Diagnostics > Dispense test with test notes, and put the ATM back in service only when the test passes.

## Cassette not detected (A-1002)
Reseat the cassette and check that the cassette ID switch matches the configured denomination. Clean the cassette connector contacts. If the cassette is still not detected, replace it and record both serial numbers.

## Reject bin full (A-1004)
Empty the reject bin, count and log the notes with the second person, and reset the reject counter in the supervisor menu.

## Escalation
Escalate to level 2 if the jam repeats within 24 hours, or if notes are damaged inside the safe.
