#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# BioSTEAM: The Biorefinery Simulation and Techno-Economic Analysis Modules
# Copyright (C) 2020, Yoel Cortes-Pena <yoelcortes@gmail.com>
# Bioindustrial-Park: BioSTEAM's Premier Biorefinery Models and Results
# Copyright (C) 2020, Yalin Li <yalinli2@illinois.edu>,
# Sarang Bhagwat <sarangb2@illinois.edu>, and Yoel Cortes-Pena (this biorefinery)
# 
# This module is under the UIUC open-source license. See 
# github.com/BioSTEAMDevelopmentGroup/biosteam/blob/master/LICENSE.txt
# for license details.

"""
Created on Wed Jul 22 20:02:49 2020

Modified from the biorefineries constructed in [1] and [2] for the production of
lactic acid from lignocellulosic feedstocks

[1] Cortes-Peña et al., BioSTEAM: A Fast and Flexible Platform for the Design, 
    Simulation, and Techno-Economic Analysis of Biorefineries under Uncertainty. 
    ACS Sustainable Chem. Eng. 2020, 8 (8), 3302–3310. 
    https://doi.org/10.1021/acssuschemeng.9b07040
    
[2] Li et al., Tailored Pretreatment Processes for the Sustainable Design of
    Lignocellulosic Biorefineries across the Feedstock Landscape. Submitted.
    July, 2020.

@author: yalinli_cabbi
"""


# %% 

# =============================================================================
# Setup
# =============================================================================

import numpy as np
import pandas as pd
import biosteam as bst
from biosteam.utils import TicToc
from lactic import system
from lactic.utils import set_yield

R301 = system.R301
R401 = system.R401
S402 = system.S402


# %% 

# =============================================================================
# Evaluate system at different lactic acid titer and yield (conversion),
# using either regular strain (need lime addition during fermentation to neutralize
# produced lactic acid) or acid-resistent strain (no neutralization need)
# =============================================================================

# Initiate a timer
timer = TicToc('timer')
timer.tic()

titer_range = np.linspace(40, 140, 11)
yield_range = np.linspace(0.3, 1, 15)
limits = [[], [], []]

R302 = system.R302
lactic_acid = system.lactic_acid
lactic_sys = system.lactic_sys
lactic_tea = system.lactic_tea

def solve_TEA():
    for i in range(3):
        lactic_acid.price = system.lactic_tea.solve_price(lactic_acid)
    return lactic_acid.price

def update_productivity(productivity):
    R301.productivity = productivity
    R302.productivity = productivity * R302.ferm_ratio
    for unit in (R301, R302):
        unit._design()
        unit._cost()
    solve_TEA()


# %%

# =============================================================================
# Regular strain
# =============================================================================

bst.speed_up()
R301.set_titer_limit = True
R301.neutralization = True
R401.bypass = False
S402.bypass = False

run_number = 0
MPSPs_regular = [[], [], []]
NPVs_regular = [[], [], []]

print('\n-------- Regular Strain --------')
for i in titer_range:
    for j in yield_range:
        limits[0].append(i)
        limits[1].append(j)
        # Baseline productivity
        R301.titer_limit = i
        R301.yield_limit = j
        set_yield(j, R301, R302)
        for m in range(2):
            lactic_sys.simulate()
        limits[2].append(R301.sugar_limited_titer)
        update_productivity(0.89)
        solve_TEA()
        MPSPs_regular[0].append(lactic_acid.price)
        NPVs_regular[0].append(lactic_tea.NPV)
        # Alternative productivities, productivity only affects reactor sizing
        # thus no need to simulate the system again
        update_productivity(0.18)
        solve_TEA()        
        MPSPs_regular[1].append(lactic_acid.price)
        NPVs_regular[1].append(lactic_tea.NPV) 
        update_productivity(1.92)
        solve_TEA()        
        MPSPs_regular[2].append(lactic_acid.price)
        NPVs_regular[2].append(lactic_tea.NPV)
        run_number += 1
        print(f'Run #{run_number}: {timer.elapsed_time:.0f} sec')

regular_data = pd.DataFrame({
    ('Limits', 'Yield [g/g]'): limits[1],
    ('Limits', 'Titer [g/L]'): limits[0],
    ('Limits', 'Sugar-limited titer [g/L]'): limits[2],
    ('Productivity=0.89 [g/L/hr] (baseline)', 'Minimum product selling price [$/kg]'):
        MPSPs_regular[0],
    ('Productivity=0.89 [g/L/hr] (baseline)', 'Net present value [$]'):
        NPVs_regular[0],
    ('Productivity=0.18 [g/L/hr] (min)', 'Minimum product selling price [$/kg]'):
        MPSPs_regular[1],
    ('Productivity=0.18 [g/L/hr] (min)', 'Net present value [$]'):
        NPVs_regular[1],
    ('Productivity=1.92 [g/L/hr] (max)', 'Minimum product selling price [$/kg]'):
        MPSPs_regular[2],
    ('Productivity=1.92 [g/L/hr] (max)', 'Net present value [$]'):
        NPVs_regular[2]
    })


# %%

# =============================================================================
# Acid-resistant strain    
# =============================================================================

bst.speed_up()
R301.set_titer_limit = True
R301.neutralization = False
R401.bypass = True
S402.bypass = True

limits = [[], [], []]
MPSPs_acid_resistant = [[], [], []]
NPVs_acid_resistant = [[], [], []]

run_number = 0

print('\n-------- Acid-resistant Strain --------')
for i in titer_range:
    for j in yield_range:
        limits[0].append(i)
        limits[1].append(j)
        # Baseline productivity
        R301.titer_limit = i
        R301.yield_limit = j
        set_yield(j, R301, R302)
        for m in range(2):
            lactic_sys.simulate()
        limits[2].append(R301.sugar_limited_titer)
        update_productivity(0.89)
        solve_TEA()
        MPSPs_acid_resistant[0].append(lactic_acid.price)
        NPVs_acid_resistant[0].append(lactic_tea.NPV)
        # Alternative productivities, productivity only affects reactor sizing
        # thus no need to simulate the system again
        update_productivity(0.18)
        solve_TEA()        
        MPSPs_acid_resistant[1].append(lactic_acid.price)
        NPVs_acid_resistant[1].append(lactic_tea.NPV) 
        update_productivity(1.92)
        solve_TEA()        
        MPSPs_acid_resistant[2].append(lactic_acid.price)
        NPVs_acid_resistant[2].append(lactic_tea.NPV)
        run_number += 1
        print(f'Run #{run_number}: {timer.elapsed_time:.0f} sec')

acid_resistent_data = pd.DataFrame({
    ('Limits', 'Yield [g/g]'): limits[1],
    ('Limits', 'Titer [g/L]'): limits[0],
    ('Limits', 'Sugar-limited titer [g/L]'): limits[2],
    ('Productivity=0.89 [g/L/hr] (baseline)', 'Minimum product selling price [$/kg]'):
        MPSPs_acid_resistant[0],
    ('Productivity=0.89 [g/L/hr] (baseline)', 'Net present value [$]'):
        NPVs_acid_resistant[0],
    ('Productivity=0.18 [g/L/hr] (min)', 'Minimum product selling price [$/kg]'):
        MPSPs_acid_resistant[1],
    ('Productivity=0.18 [g/L/hr] (min)', 'Net present value [$]'):
        NPVs_acid_resistant[1],
    ('Productivity=1.92 [g/L/hr] (max)', 'Minimum product selling price [$/kg]'):
        MPSPs_acid_resistant[2],
    ('Productivity=1.92 [g/L/hr] (max)', 'Net present value [$]'):
        NPVs_acid_resistant[2]
    })

    
# %%

'''Output to Excel'''
with pd.ExcelWriter('4_fermentation.xlsx') as writer:
    regular_data.to_excel(writer, sheet_name='Regular')
    acid_resistent_data.to_excel(writer, sheet_name='Acid-resistant')

time = timer.elapsed_time / 60
print(f'\nSimulation time for {run_number} runs is: {time:.1f} min')


