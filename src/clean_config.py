"""Every threshold and constant used by src/clean.py, in one place.

Each value is justified in docs/cleaning_report.md, section 5 ("Constants").
Changing a value and running `python src/clean.py` again changes exactly the flags that value controls.
"""

# Units
AU_KM = 149_597_870.7          # km in one astronomical unit (IAU 2012 exact definition)

# Unusual values: modified z-score, per group (orbit class for orbits, orbiting body for approaches)
MAD_SCALE = 0.6745             # makes the median absolute deviation comparable to a standard deviation
Z_LIMIT = 3.5                  # |z| above this is unusual_high / unusual_low (Iglewicz & Hoaglin, 1993)

# Invalid values: physical and definitional limits
H_MIN, H_MAX = 0.0, 35.0       # absolute magnitude: brightest NEA ~9 (Ganymed), faintest ever observed ~33
INCLINATION_MAX_DEG = 180.0    # inclination is defined on 0..180 degrees
ECCENTRICITY_MAX = 1.0         # e >= 1 is not a closed orbit, so not an asteroid in orbit around the Sun
AU_TOLERANCE = 0.001           # AU (~150,000 km) allowed between perihelion and a(1-e); values carry 6+ decimals
VELOCITY_MAX_KM_S = 130.0      # fastest possible inner-planet encounter: solar escape speed at Mercury (~67)
                               # plus Mercury's top orbital speed (~59), rounded up
UNCERTAINTY_CODES = range(10)  # NASA's orbit uncertainty parameter U is an integer 0..9

# Hazard label: NASA/CNEOS definition of a potentially hazardous asteroid
PHA_H_MAX = 22.0               # absolute magnitude H <= 22.0 ...
PHA_MOID_MAX_AU = 0.05         # ... and Earth minimum orbit intersection distance <= 0.05 AU
