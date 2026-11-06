We use an Arduino Due as an oscilloscope and signal generator for automation work. 

Its pins are 3.3 volts with no protection, so we need a front end: two scope
inputs of plus or minus 5 volts, one generator output of plus or minus 1
volt, and a jumper for differential mode.

Design it in KiCad, using the proto board, whose KiCad file we provided. 

Low cost is the key: common parts, hand-solderable, with a
bill of materials and a total. Prove it by simulation in ngspice, with one
command that reruns everything. 

The requirement document is given with our current firmware and hardware setup are in general terms. 

For the converter, DAC and pin limits, read the SAM3X datasheet and the Due files yourselves. 

If a requirement looks wrong or can't be met, tell us. Don't relax it quietly.

Send us the KiCad project, with component poped on board.

Send us your simulation model, a pass/fail table, the parts list, and a validation plan.