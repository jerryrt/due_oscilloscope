"""The master clock the host assumes, in one place.

Every RC divides MCK/2, so a host that holds a different number than the
board it talks to computes the wrong RC from every rate it names, and the
board accepts it. The firmware divides this in integer arithmetic, so it
must be the nominal MCK and never the measured one.

90 MHz is the default. DUE_MCK_HZ=78000000 matches an image built with
-DFIRMWARE_MCK_HZ=78000000.

Standard library only, because the fake daemon and the front end's demo
forms run without the rest of the environment (`gui --spawn-fake`), and
three modules had each read the variable for themselves.
"""
import os

MCK_HZ = int(os.environ.get("DUE_MCK_HZ", 90_000_000))
TC_CLOCK_HZ = MCK_HZ // 2          # TIMER_CLOCK1 is MCK/2
