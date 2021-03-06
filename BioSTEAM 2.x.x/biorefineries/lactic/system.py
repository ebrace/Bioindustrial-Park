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
Created on Mon Dec 30 09:15:23 2019

Modified from the biorefineries constructed in [1] and [2] for the production of
lactic acid from lignocellulosic feedstocks

[1] Cortes-Peña et al., BioSTEAM: A Fast and Flexible Platform for the Design, 
    Simulation, and Techno-Economic Analysis of Biorefineries under Uncertainty. 
    ACS Sustainable Chem. Eng. 2020, 8 (8), 3302–3310. 
    https://doi.org/10.1021/acssuschemeng.9b07040
    
[2] Li et al., Tailored Pretreatment Processes for the Sustainable Design of
    Lignocellulosic Biorefineries across the Feedstock Landscape. Submitted.
    July, 2020.

Naming conventions:
    D = Distillation column
    F = Flash tank
    H = Heat exchange
    M = Mixer
    P = Pump (including conveying belt)
    R = Reactor
    S = Splitter (including solid/liquid separator)
    T = Tank or bin for storage
    U = Other units
    PS = Process specificiation, not physical units, but for adjusting streams

Processes:
    100: Feedstock preprocessing
    200: Pretreatment
    300: Conversion
    400: Separation
    500: Wastewater treatment
    600: Facilities

@author: yalinli_cabbi
"""


# %% Setup

import biosteam as bst
import thermosteam as tmo
from flexsolve import aitken_secant, IQ_interpolation
from biosteam import System
from biosteam.process_tools import UnitGroup
from thermosteam import Stream
from lactic import units, facilities
from lactic.hx_network import HX_Network
from lactic.process_settings import price
from lactic.utils import baseline_feedflow, set_yield, find_split, splits_df
from lactic.chemicals import chems, chemical_groups, soluble_organics, combustibles
from lactic.tea import LacticTEA

flowsheet = bst.Flowsheet('lactic')
bst.main_flowsheet.set_flowsheet(flowsheet)
bst.CE = 541.7 # year 2016

# Set default thermo object for the system
tmo.settings.set_thermo(chems)

# These settings are sufficient to get lactic acid price error below $0.005/kg
# after three simulations
System.converge_method = 'fixed-point' # aitken isn't stable
System.maxiter = 1500
System.molar_tolerance = 0.1


# %% 

# =============================================================================
# Feedstock preprocessing
# =============================================================================

feedstock = Stream('feedstock', baseline_feedflow.copy(),
                    units='kg/hr', price=price['Feedstock'])

U101 = units.FeedstockPreprocessing('U101', ins=feedstock)
# Handling costs/utilities included in feedstock cost thus not considered here
U101.cost_items['System'].cost = 0
U101.cost_items['System'].kW = 0

process_groups = []
feedstock_group = UnitGroup('feedstock_group', units=(U101,))
process_groups.append(feedstock_group)


# %% 

# =============================================================================
# Pretreatment streams
# =============================================================================

# For pretreatment, 93% purity
sulfuric_acid_T201 = Stream('sulfuric_acid_T201', units='kg/hr')
# To be mixed with sulfuric acid, flow updated in SulfuricAcidMixer
water_M201 = Stream('water_M201', T=114+273.15, units='kg/hr')

# To be used for feedstock conditioning
water_M202 = Stream('water_M202', T=95+273.15, units='kg/hr')

# To be added to the feedstock/sulfuric acid mixture, flow updated by the SteamMixer
steam_M203 = Stream('steam_M203', phase='g',T=268+273.15, P=13*101325, units='kg/hr')

# For neutralization of pretreatment hydrolysate
ammonia_M205 = Stream('ammonia_M205', phase='l', units='kg/hr')
# To be used for ammonia addition, flow updated by AmmoniaMixer
water_M205 = Stream('water_M205', units='kg/hr')


# =============================================================================
# Pretreatment units
# =============================================================================

# Prepare sulfuric acid
feedstock_dry_mass = feedstock.F_mass - feedstock.imass['H2O']
T201 = units.SulfuricAcidAdditionTank('T201', ins=sulfuric_acid_T201,
                                      feedstock_dry_mass=feedstock_dry_mass)

M201 = units.SulfuricAcidMixer('M201', ins=(T201-0, water_M201))

# Mix sulfuric acid and feedstock, adjust water loading for pretreatment
M202 = units.PretreatmentMixer('M202', ins=(U101-0, M201-0, water_M202))

# Mix feedstock/sulfuric acid mixture and steam
M203 = units.SteamMixer('M203', ins=(M202-0, steam_M203), P=5.5*101325)
R201 = units.AcidPretreatment('R201', ins=M203-0, outs=('R201_g', 'R201_l'))

# Pump bottom of the pretreatment products to the oligomer conversion tank
T202 = units.BlowdownTank('T202', ins=R201-1)
T203 = units.OligomerConversionTank('T203', ins=T202-0)
F201 = units.PretreatmentFlash('F201', ins=T203-0,
                               outs=('F201_waste_vapor', 'F201_to_fermentation'),
                               P=101325, Q=0)

M204 = bst.units.Mixer('M204', ins=(R201-0, F201-0))
H201 = units.WasteVaporCondenser('H201', ins=M204-0,
                                 outs='condensed_pretreatment_waste_vapor',
                                 V=0, rigorous=True)

# Neutralize pretreatment hydrolysate
M205 = units.AmmoniaMixer('M205', ins=(ammonia_M205, water_M205))
def update_ammonia_and_mix():
    hydrolysate = F201.outs[1]
    # Load 10% extra
    ammonia_M205.imol['NH4OH'] = (2*hydrolysate.imol['H2SO4']) * 1.1
    M205._run()
M205.specification = update_ammonia_and_mix

T204 = units.AmmoniaAdditionTank('T204', ins=(F201-1, M205-0))
P201 = units.HydrolysatePump('P201', ins=T204-0)

pretreatment_group = UnitGroup('pretreatment_group',
                               units=(T201, M201, M202, M203, 
                                      R201, T202, T203, F201,
                                      M204, H201,
                                      M205, T204, P201))
process_groups.append(pretreatment_group)


# %% 

# =============================================================================
# Conversion streams
# =============================================================================

# flow updated in EnzymeHydrolysateMixer
enzyme_R301 = Stream('enzyme_R301', units='kg/hr', price=price['Enzyme'])
# Used to adjust enzymatic hydrolysis solid loading, flow updated in EnzymeHydrolysateMixer
water_R301 = Stream('water_R301', units='kg/hr')
# Corn steep liquor as nitrogen nutrient for microbes, flow updated in R301
CSL_R301 = Stream('CSL_R301', units='kg/hr')
# Lime for neutralization of produced acid
lime_R301 = Stream('lime_R301', units='kg/hr')

# =============================================================================
# Conversion units
# =============================================================================

# Cool hydrolysate down to fermentation temperature at 50°C
H301 = units.HydrolysateCooler('H301', ins=P201-0, T=50+273.15)

# Mix enzyme with the cooled pretreatment hydrolysate
M301 = units.EnzymeHydrolysateMixer('M301', ins=(H301-0, enzyme_R301, water_R301))

R301 = units.SaccharificationAndCoFermentation('R301',
                                               ins=(M301-0, '', CSL_R301, lime_R301),
                                               outs=('fermentation_effluent', 
                                                     'sidedraw'),
                                               neutralization=True,
                                               set_titer_limit=False)

R302 = units.SeedTrain('R302', ins=R301-1, outs=('seed',))

T301 = units.SeedHoldTank('T301', ins=R302-0, outs=1-R301)

seed_recycle = System('seed_recycle', path=(R301, R302, T301), recycle=R302-0)

# Adjust titer 
def titer_at_yield(lactic_yield):
    set_yield(lactic_yield, R301, R302)
    seed_recycle._run()
    return R301.effluent_titer-R301.titer_limit

def adjust_titer_yield():
    if R301.set_titer_limit:
        lactic_yield = IQ_interpolation(
            f=titer_at_yield, x0=0, x1=R301.yield_limit,
            xtol=0.001, ytol=0.01, maxiter=50,
            args=(), checkbounds=False)
        set_yield(lactic_yield, R301, R302)
        seed_recycle._run()
PS301 = bst.units.ProcessSpecification('PS301', ins=R301-0,
                                        specification=adjust_titer_yield)

conversion_group = UnitGroup('conversion_group',
                              units=(H301, M301, R301, R302, T301, PS301))
process_groups.append(conversion_group)


# %% 

# =============================================================================
# Separation streams
# =============================================================================

# flow updated in AcidulationReactor
sulfuric_acid_R401 = Stream('sulfuric_acid_R401', units='kg/hr')

gypsum = Stream('gypsum', units='kg/hr', price=price['Gypsum'])

# Ethanol for esterification reaction, flow updated in EsterificationReactor
ethanol_R402 = Stream('ethanol_R402', units='kg/hr')

# For ester hydrolysis
water_R403 = Stream('water_R403', units='kg/hr')

# =============================================================================
# Separation units
# =============================================================================

# Remove solids from fermentation broth
S401_index = [splits_df.index[0]] + splits_df.index[2:].to_list()
S401_cell_mass_split = [splits_df['stream_571'][0]] + splits_df['stream_571'][2:].to_list()
S401_filtrate_split = [splits_df['stream_535'][0]] + splits_df['stream_535'][2:].to_list()
S401 = units.CellMassFilter('S401', ins=PS301-0, outs=('cell_mass', ''),
                            moisture_content=0.35,
                            split=find_split(S401_index,
                                             S401_cell_mass_split,
                                             S401_filtrate_split,
                                             chemical_groups))

# Ca(LA)2 + H2SO4 --> CaSO4 + 2 LA
R401 = units.AcidulationReactor('R401', ins=(S401-1, sulfuric_acid_R401),
                                P=101325, tau=0.5, V_wf=0.8, length_to_diameter=2,
                                kW_per_m3=0.985, wall_thickness_factor=1.5,
                                vessel_material='Stainless steel 316',
                                vessel_type='Vertical')
R401_P = bst.units.Pump('R401_P', ins=R401-0)

# Moisture content (20%) and gypsum removal (99.5%) on Page 24 of Aden et al.
S402_index = S401_index + ['Gypsum']
S402_gypsum_split = S401_cell_mass_split + [0.995]
S402_filtrate_split = S401_filtrate_split + [0.005]
S402 = units.GypsumFilter('S402', ins=R401_P-0,
                          moisture_content=0.2,
                          split=find_split(S402_index,
                                           S402_gypsum_split,
                                           S402_filtrate_split,
                                           chemical_groups),
                          outs=(gypsum, ''))

# Separate out the majority of water
F401 = bst.units.Flash('F401', ins=S402-1, outs=('F401_g', 'F401_l'), T=379, P=101325,
                       vessel_material='Stainless steel 316')
# To avoid flash temperature lower than inlet temperature
def adjust_F401_T():
    if F401.ins[0].T > F401.T:
        F401.T = F401.ins[0].T
    else: F401.T = 379
    F401._run()
F401.specification = adjust_F401_T

# Condense waste vapor for recycling
F401_H = bst.units.HXutility('F401_H', ins=F401-0, V=0, rigorous=True)
F401_P = bst.units.Pump('F401_P', ins=F401-1)

# Separate out persisting water and more volatile components to 
# improve conversion of downstream esterification 
D401 = bst.units.BinaryDistillation('D401', ins=F401_P-0,
                                    outs=('D401_g_volatiles', 'D401_l_LA'),
                                    LHK=('AceticAcid', 'Furfural'),
                                    is_divided=True,
                                    product_specification_format='Recovery',
                                    Lr=0.99, Hr=0.5, k=1.2,
                                    vessel_material='Stainless steel 316')
D401_H = bst.units.HXutility('D401_H', ins=D401-0, V=0, rigorous=True)
D401_P = bst.units.Pump('D401_P', ins=D401-1)

# LA + EtOH --> EtLA + H2O
# R402.ins[0] is volatile-removed fermentation broth, ~50% w/w conc. LA feed,
# R402.ins[1] is ethanol recycled from D402,
# R402.ins[2] is latic acid recycled from D403,
# R402.ins[3] is supplementary ethanol,
# R402.ins[4] is ethanol recycled from D404
R402 = units.Esterification('R402', ins=(D401_P-0, '', 'D403_l_recycled', 
                                         ethanol_R402, ''),
                            V_wf=0.8, length_to_diameter=2,
                            kW_per_m3=0.985, wall_thickness_factor=1,
                            vessel_material='Stainless steel 316',
                            vessel_type='Vertical')
# Increase pressure as the solution can be very thick for some designs
R402_P = bst.units.Pump('R402_P', ins=R402-0, dP_design=5*101325)

# Distillation for recycling unreacted ethanol; 
# keep as BinaryDistillation so top product's ethanol doesn't exceed azeotropic conc. 
# during Monte Carlo
D402 = bst.units.BinaryDistillation('D402', ins=R402_P-0, outs=('D402_g', 'D402_l'),
                                    LHK=('Ethanol', 'H2O'),
                                    is_divided=True,
                                    product_specification_format='Recovery',
                                    Lr=0.99, Hr=0.45, k=1.2,
                                    vessel_material='Stainless steel 316')

D402_H = bst.units.HXutility('D402_H', ins=D402-0, outs=1-R402, V=0, rigorous=True)
D402_P = bst.units.Pump('D402_P', ins=D402-1)

# Principal recovery step; EtLA separated from less volatile impurities
# N.B.: S403's Lr and Hr are great candidate parameters for formal optimization
D403 = bst.units.BinaryDistillation('D403', ins=D402_P-0, outs=('D403_g', 'D403_l'),
                                LHK=('EthylLactate', 'LacticAcid'),
                                is_divided=True,
                                product_specification_format='Recovery',
                                Lr=0.995, Hr=0.9995, k=1.2,
                                vessel_material='Stainless steel 316')

# Condense reactants into liquid phase
D403_H = bst.units.HXutility('D403_H', ins=D403-0, V=0, rigorous=True)
D403_P = bst.units.Pump('D403_P', ins=D403-1)

# S403.ins is the bottom of D403 (LA recycle stream), not the top (EtLA-rich product stream)
# S403.outs[0] is recycled back to R402, the EsterificationReactor
# S403.outs[1] is discarded to prevent accumulation
# It might have been a better idea to mix this with R301-0,
# but currently not possible to simulate this recycle stream
S403 = bst.units.Splitter('S403',ins=D403_P-0, outs=(2-R402, 'D403_l_to_waste'), 
                          split=0.97)

# EtLA + H2O --> LA + EtOH
# R403.ins[0] is the main EtLA feed,
# R403.ins[1] is supplementary water (almost never needed)
# R403.ins[2] is recycled water from top of F401 (minor EtLA and LA)
# R403.ins[3] is recycled water from top of F402 (some EtLA and LA)
# R403.outs[1] is the discarded fraction of R403.ins[2]
R403 = units.HydrolysisReactor('R403', ins=(D403_H-0, water_R403, F401_H-0, ''),
                               tau=4, V_wf=0.8, length_to_diameter=2,
                               kW_per_m3=0.985, wall_thickness_factor=1,
                               vessel_material='Stainless steel 316',
                               vessel_type='Vertical')
R403_P = bst.units.Pump('R403_P', ins=R403-0)

# Distillation to recycle ethanol formed by hydrolysis of EtLA
D404 = bst.units.ShortcutColumn('D404', R403_P-0, outs=('D404_g', 'D404_l'),
                                LHK=('Ethanol', 'H2O'),
                                product_specification_format='Recovery',
                                is_divided=True,
                                Lr=0.9, Hr=0.9935, k=1.2,
                                vessel_material='Stainless steel 316')

D404_H = bst.units.HXutility('D404_H', ins=D404-0, outs=4-R402, V=0, rigorous=True)
D404_P = bst.units.Pump('D404_P', ins=D404-1)

# To get the final acid product
F402 = bst.units.Flash('F402', ins=D404_P-0, V=0.9, P=101325,
                       vessel_material='Stainless steel 316')

def purity_at_V(V):
    F402.V = V
    F402._run()
    purity = F402.outs[1].get_mass_composition('LacticAcid')
    return purity-0.88

def adjust_F402_V():
    H2O_molfrac = D404_P.outs[0].get_molar_composition('H2O')
    V0 = H2O_molfrac
    F402.V = aitken_secant(f=purity_at_V, x0=V0, x1=V0+0.001,
                            xtol=0.001, ytol=0.001, maxiter=50,
                            args=())
F402.specification = adjust_F402_V

F402_H1 = bst.units.HXutility('F402_H1', ins=F402-0, outs=3-R403, V=0, rigorous=True)
F402_H2 = bst.units.HXutility('F402_H2', ins=F402-1, T=345)
F402_P = bst.units.Pump('F402_P', ins=F402_H2-0)

M401 = bst.units.Mixer('M401', ins=(D401_H-0, S403-1))
M401_P = bst.units.Pump('M401_P', ins=M401-0, outs='condensed_separation_waste_vapor')

separation_group = UnitGroup('separation_group',
                              units=(S401, R401, R401_P, S402, 
                                     F401, F401_H, F401_P,
                                     D401, D401_H, D401_P,
                                     R402, R402_P,
                                     D402, D402_H, D402_P,
                                     D403, D403_H, D403_P, S403,
                                     R403, R403_P,
                                     D404, D404_H, D404_P,
                                     F402, F402_H1, F402_H2, F402_P,
                                     M401, M401_P))
process_groups.append(separation_group)


# %% 

# =============================================================================
# Wastewater treatment streams
# =============================================================================

caustic_R502 = Stream('caustic_R502', units='kg/hr', price=price['NaOH'])
polymer_R502 = Stream('polymer_R502', units='kg/hr', price=price['WWT polymer'])
air_R502 = Stream('air_R502', phase='g', units='kg/hr')

# =============================================================================
# Wastewater treatment units
# =============================================================================

# Mix waste liquids for treatment
M501 = bst.units.Mixer('M501', ins=(H201-0, M401_P-0, R402-1, R403-1))

R501 = units.AnaerobicDigestion('R501', ins=M501-0,
                                outs=('biogas', 'anaerobic_treated_water', 
                                      'anaerobic_sludge'),
                                reactants=soluble_organics,
                                split=find_split(splits_df.index,
                                                 splits_df['stream_611'],
                                                 splits_df['stream_612'],
                                                 chemical_groups),
                                T=35+273.15)

R502 = units.AerobicDigestion('R502', ins=(R501-1, '', caustic_R502, 'ammonia_R601',
                                           polymer_R502, air_R502),
                              outs=('aerobic_vent', 'aerobic_treated_water'),
                              reactants=soluble_organics,
                              caustic_mass=2252*U101.feedstock_flow_rate/2205,
                              need_ammonia=False)

# Membrane bioreactor to split treated wastewater from R502
S501 = units.MembraneBioreactor('S501', ins=R502-1,
                                outs=('membrane_treated_water', 'membrane_sludge'),
                                split=find_split(splits_df.index,
                                                 splits_df['stream_624'],
                                                 splits_df['stream_625'],
                                                 chemical_groups))

# Recycled sludge stream of memberane bioreactor, the majority of it (96%)
# goes to aerobic digestion
S502 = bst.units.Splitter('S502', ins=S501-1, outs=('to_aerobic_digestion', ''),
                          split=0.96)

S503 = units.BeltThickener('S503', ins=(R501-2, S502-1),
                           outs=('S503_centrate', 'S503_solids'))

# Sludge centrifuge to separate water (centrate) from sludge
S504 = units.SludgeCentrifuge('S504', ins=S503-1, outs=('S504_centrate',
                                                        'S504_CHP'))

# Mix recycles to aerobic digestion
M502 = bst.units.Mixer('M502', ins=(S502-0, S503-0, S504-0), outs=1-R502)

# Reverse osmosis to treat membrane separated water
S505 = units.ReverseOsmosis('S505', ins=S501-0, outs=('recycled_water', 'brine'))

wastewater_group = UnitGroup('wastewater_group',
                             units=(M501, R501,
                                    R502, S501, S502, S503, S504, M502,
                                    S505))
process_groups.append(wastewater_group)


# %% 

# =============================================================================
# Facilities streams
# =============================================================================

# Final product
lactic_acid = Stream('lactic_acid', units='kg/hr')

# Process chemicals
sulfuric_acid = Stream('sulfuric_acid', units='kg/hr', price=price['Sulfuric acid'])
ammonia = Stream('ammonia', units='kg/hr', price=price['NH4OH'])
CSL = Stream('CSL', units='kg/hr', price=price['CSL'])
lime = Stream('lime', units='kg/hr', price=price['Lime'])
ethanol = Stream('ethanol', units='kg/hr', price=price['Ethanol'])

# Chemicals used/generated in CHP
lime_CHP = Stream('lime_CHP', units='kg/hr', price=price['Lime'])
ammonia_CHP = Stream('ammonia_CHP', units='kg/hr',
                     NH4OH=1054*35.046/17.031*U101.feedstock_flow_rate/2205)
boiler_chems = Stream('boiler_chems', units='kg/hr', price=price['Boiler chems'])
baghouse_bag = Stream('baghouse_bag', units='kg/hr', price=price['Baghouse bag'])
# Supplementary natural gas for CHP if produced steam not enough for regenerating
# all steam streams required by the system
natural_gas = Stream('natural_gas', units='kg/hr', price=price['Natural gas'])
ash = Stream('ash', units='kg/hr', price=price['Ash disposal'])

cooling_tower_chems = Stream('cooling_tower_chems', units='kg/hr',
                             price=price['Cooling tower chems'])

system_makeup_water = Stream('system_makeup_water', price=price['Makeup water'])

firewater_in = Stream('firewater_in', 
                      Water=8021*U101.feedstock_flow_rate/2205, units='kg/hr')

# Clean-in-place
CIP_chems_in = Stream('CIP_chems_in', Water=145*U101.feedstock_flow_rate/2205, 
                      units='kg/hr')

# Air needed for multiple processes (including enzyme production that was not included here),
# not rigorously modeled, only scaled based on plant size
plant_air_in = Stream('plant_air_in', phase='g', units='kg/hr',
                      N2=0.79*1372608*U101.feedstock_flow_rate/2205,
                      O2=0.21*1372608*U101.feedstock_flow_rate/2205)

# =============================================================================
# Facilities units
# =============================================================================

# 7-day storage time similar to ethanol's in ref [3]
T601 = bst.units.StorageTank('T601', ins=F402_P-0, tau=7*24, V_wf=0.9,
                              vessel_type='Floating roof',
                              vessel_material='Stainless steel')
T601.line = 'Lactic acid storage'
T601_P = bst.units.Pump('T601_P', ins=T601-0, outs=lactic_acid)

T602 = units.SulfuricAcidStorage('T602', ins=sulfuric_acid)
T602_S = bst.units.ReversedSplitter('T602_S', ins=T602-0, 
                                    outs=(sulfuric_acid_T201, sulfuric_acid_R401))

T603 = units.AmmoniaStorage('T603', ins=ammonia)
T603_S = bst.units.ReversedSplitter('T603_S', ins=T603-0,
                                    outs=(ammonia_M205, ammonia_CHP))

T604 = units.CSLstorage('T604', ins=CSL, outs=CSL_R301)

# Lime used in CHP not included here for sizing, as it's relatively minor (~6%)
# compared to lime used in fermentation and including it will cause problem in
# simulation (facilities simulated after system)
T605 = units.LimeStorage('T605', ins=lime, outs=lime_R301)

# 7-day storage time similar to ethanol's in ref [3]
T606 = units.SpecialStorage('T606', ins=ethanol, tau=7*24, V_wf=0.9,
                            vessel_type='Floating roof',
                            vessel_material='Carbon steel')
T606.line = 'Ethanol storage'
T606_P = units.SpecialPump('T606_P', ins=T606-0, outs=ethanol_R402)

T607 = units.FireWaterStorage('T607', ins=firewater_in, outs='firewater_out')

# Mix solid wastes to CHP
M601 = bst.units.Mixer('M601', ins=(S401-0, S504-1), outs='wastes_to_CHP')

# Blowdown is discharged
CHP = facilities.CHP('CHP', ins=(M601-0, R501-0, lime_CHP, ammonia_CHP,
                                 boiler_chems, baghouse_bag, natural_gas,
                                 'boiler_feed_water'),
                     B_eff=0.8, TG_eff=0.85, combustibles=combustibles,
                     side_streams_to_heat=(water_M201, water_M202, steam_M203),
                     outs=('gas_emission', ash, 'boiler_blowdown_water'))

# Blowdown is discharged
CT = facilities.CT('CT', ins=('return_cooling_water', cooling_tower_chems,
                              'CT_makeup_water'),
                   outs=('process_cooling_water', 'cooling_tower_blowdown'))

# All water used in the system, here only consider water usage,
# if heating needed, then heeating duty required is considered in CHP
process_water_streams = (water_M201, water_M202, steam_M203, water_M205,
                         water_R301, water_R403, CHP.ins[-1], CT.ins[-1])

PWC = facilities.PWC('PWC', ins=(system_makeup_water, S505-0),
                     process_water_streams=process_water_streams,
                     outs=('process_water', 'discharged_water'))

ADP = facilities.ADP('ADP', ins=plant_air_in, outs='plant_air_out',
                     ratio=U101.feedstock_flow_rate/2205)
CIP = facilities.CIP('CIP', ins=CIP_chems_in, outs='CIP_chems_out')

# Heat exchange network
HXN = HX_Network('HXN')

HXN_group = UnitGroup('HXN_group', units=(HXN,))
process_groups.append(HXN_group)

CHP_group = UnitGroup('CHP_group', units=(CHP,))
process_groups.append(CHP_group)

CT_group = UnitGroup('CT_group', units=(CT,))
process_groups.append(CT_group)

facilities_no_hu_group = UnitGroup('facilities_no_hu_group',
                                   units=(T601, T601_P, T602, T602_S,
                                          T603, T603_S, T604,
                                          T605, T606, T606_P, T607,
                                          M601, PWC, ADP, CIP))
process_groups.append(facilities_no_hu_group)


# %% 

# =============================================================================
# Complete system
# =============================================================================

lactic_sys = System('lactic_sys',
    [
   # Feedstock preprocessing
      U101,
      
   # Pretreatment
      T201, M201, # sulfuric acid mixing and addition
      M202, # feedstock mixing
      M203, R201, # pretreatment 
      T202, T203,# blowdown and oligomer conversion
      F201, # pretreatment flash
      M204, H201, # waste vapor mixing and condensation
      M205, T204, P201, # ammonia addition
      
   # Conversion
      H301, # hydrolysate cooler
      M301, # enzyme addition
      seed_recycle, # fermenter, seed train, and seed holding tank
      PS301, # adjust fermentation titer and yield
      
   # Separation
      S401, # cell mass filter
      R401, R401_P, # acidulation
      S402, # gypsum filter
      F401, F401_H, F401_P, # separate water
      D401, D401_H, D401_P, # separate other volatiles
      System('esterification_recycle',
        [System('outer_loop_acid_and_ester_recycle',
            [System('inner_loop_ethanol_cycle',
                [R402, R402_P, # esterification of lactic acid
                  D402, D402_H, D402_P], # separate out ethanol
                recycle=D402_H-0), # recycle ethanol
              D403, D403_H, D403_P, S403], # separate out acid and ester
            recycle=S403-0), # recycle acid and ester
          System('hydrolysis_recycle',
                [R403, R403_P, # hydrolysis of ester
                 D404, D404_H, D404_P, # separate out ethanol for recylcing
                 F402, F402_H1], # separate out volatiles, final purification
                recycle=F402_H1-0), # recycle ester
          ],
          recycle=D404_H-0), # recycle ethanol
      F402_H2, F402_P,
      M401, M401_P, # separation waste mixing

   # Wastewater treatment
      M501, R501, # anaerobic digestion
      System('wastewater_treatment_recycle',
        [R502, # aerobic digestion
         S501, S502, # membrane bioreactor
         S503, # belt thickener
         S504, M502], # sludge centrifuge
        recycle=M502-0), # recycle sludge
      S505, # reverse osmosis

   # Facilities
      T601, T601_P, # lactic acid storage
      T602_S, T602, # sulfuric acid storage
      T603_S, T603, # ammonia storage
      T604, # CSL storage
      T605, # lime storage
      T606, T606_P, # ethanol storage
      T607, # firewater storage
      M601], # CHP mixer
    facilities=(HXN, CHP, CT, PWC, ADP, CIP))

CHP_sys = System('CHP_sys', path=(CHP,))

# =============================================================================
# TEA
# =============================================================================

ISBL_units = set((*pretreatment_group.units, *conversion_group.units,
                  *separation_group.units))
OSBL_units = list(lactic_sys.units.difference(ISBL_units))

# CHP is not included in this TEA
OSBL_units.remove(CHP)
# biosteam Splitters and Mixers have no cost
for i in OSBL_units:
    if i.__class__ == bst.units.Mixer or i.__class__ == bst.units.Splitter:
        OSBL_units.remove(i)

lactic_no_CHP_tea = LacticTEA(
        system=lactic_sys, IRR=0.10, duration=(2016, 2046),
        depreciation='MACRS7', income_tax=0.21, operating_days=0.96*365,
        lang_factor=None, construction_schedule=(0.08, 0.60, 0.32),
        startup_months=3, startup_FOCfrac=1, startup_salesfrac=0.5,
        startup_VOCfrac=0.75, WC_over_FCI=0.05,
        finance_interest=0.08, finance_years=10, finance_fraction=0.4,
        OSBL_units=OSBL_units,
        warehouse=0.04, site_development=0.09, additional_piping=0.045,
        proratable_costs=0.10, field_expenses=0.10, construction=0.20,
        contingency=0.10, other_indirect_costs=0.10, 
        labor_cost=3212962*U101.feedstock_flow_rate/2205,
        labor_burden=0.90, property_insurance=0.007, maintenance=0.03)

# Removes units, feeds, and products of CHP_sys to avoid double-counting
lactic_no_CHP_tea.units.remove(CHP)

for i in CHP_sys.feeds:
    lactic_sys.feeds.remove(i)
for i in CHP_sys.products:
    lactic_sys.products.remove(i)

# Changed to MACRS 20 to be consistent with ref [3]
CHP_tea = bst.TEA.like(CHP_sys, lactic_no_CHP_tea)
CHP_tea.labor_cost = 0
CHP_tea.depreciation = 'MACRS20'
CHP_tea.OSBL_units = (CHP,)

lactic_tea = bst.CombinedTEA([lactic_no_CHP_tea, CHP_tea], IRR=0.10)
lactic_sys._TEA = lactic_tea

# Simulate system and get results
def simulate_get_MPSP():
    lactic_sys.simulate()
    for i in range(3):
        MPSP = lactic_acid.price = lactic_tea.solve_price(lactic_acid)
    return MPSP


# %%

# =============================================================================
# Temporary codes
# =============================================================================

# R301.set_titer_limit = True
# R301.titer_limit = 30
# R301.yield_limit = 0.6

# R301.set_titer_limit = False
# set_yield(0.76, R301, R302)    
    
# MPSP = simulate_get_MPSP()
# print(f'Baseline MPSP is ${MPSP:.3f}/kg')


# for i in range(3):
#     MPSP = simulate_get_MPSP()
# print(f'MPSP is ${lactic_acid.price:.3f}/kg')


# all_units = sum((i.units for i in process_groups), ())
# for unit in all_units:
#     if not unit in lactic_sys.units:
#         print(f'{unit.ID} not in lactic_sys.units')

# for unit in lactic_sys.units:
#     if not unit in all_units:
#         print(f'{unit.ID} not in all_units')



