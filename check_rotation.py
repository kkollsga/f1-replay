#!/usr/bin/env python
"""
Simple script to check what FastF1 returns for Monaco 2024 (Round 8) rotation.
"""

import fastf1
import math

# Load Monaco 2024 session
print("Loading Monaco 2024 (Round 8) race session from FastF1...")
session = fastf1.get_session(2024, 8, 'R')
session.load()

# Get circuit info
circuit_info = session.get_circuit_info()

# Print rotation value
print(f"\nCircuit Info Rotation:")
print(f"  Raw value: {circuit_info.rotation}")
print(f"  Type: {type(circuit_info.rotation)}")
print(f"  As degrees: {circuit_info.rotation}°")
print(f"  As radians: {math.radians(circuit_info.rotation):.4f} rad")

# Print all circuit attributes
print(f"\nAll circuit_info attributes:")
for attr in sorted(dir(circuit_info)):
    if not attr.startswith('_'):
        try:
            val = getattr(circuit_info, attr)
            if not callable(val):
                print(f"  {attr}: {val}")
        except Exception as e:
            print(f"  {attr}: <error: {e}>")
