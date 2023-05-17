# conditioning and reco columns for muons

muon_cond = [
    "MGenMuon_eta",
    "MGenMuon_phi",
    "MGenMuon_pt",
    "MGenMuon_charge",
    "MGenPart_statusFlags0",
    "MGenPart_statusFlags1",
    "MGenPart_statusFlags2",
    "MGenPart_statusFlags3",
    "MGenPart_statusFlags4",
    "MGenPart_statusFlags5",
    "MGenPart_statusFlags6",
    "MGenPart_statusFlags7",
    "MGenPart_statusFlags8",
    "MGenPart_statusFlags9",
    "MGenPart_statusFlags10",
    "MGenPart_statusFlags11",
    "MGenPart_statusFlags12",
    "MGenPart_statusFlags13",
    "MGenPart_statusFlags14",
    "ClosestJet_dr",
    "ClosestJet_deta",
    "ClosestJet_dphi",
    "ClosestJet_pt",
    "ClosestJet_mass",
    "ClosestJet_EncodedPartonFlavour_light",
    "ClosestJet_EncodedPartonFlavour_gluon",
    "ClosestJet_EncodedPartonFlavour_c",
    "ClosestJet_EncodedPartonFlavour_b",
    "ClosestJet_EncodedPartonFlavour_undefined",
    "ClosestJet_EncodedHadronFlavour_b",
    "ClosestJet_EncodedHadronFlavour_c",
    "ClosestJet_EncodedHadronFlavour_light",
    "Pileup_gpudensity",
    "Pileup_nPU",
    "Pileup_nTrueInt",
    "Pileup_pudensity",
    "Pileup_sumEOOT",
    "Pileup_sumLOOT",
]

muon_names = [
    "etaMinusGen",
    "phiMinusGen",
    "ptRatio",
    "dxy",
    "dxyErr",
    "dz",
    "dzErr",
    "ip3d",
    "isGlobal",
    "isPFcand",
    "isTracker",
    "jetPtRelv2",
    "jetRelIso",
    "mediumId",
    "pfRelIso03_all",
    "pfRelIso03_chg",
    "pfRelIso04_all",
    "ptErr",
    "sip3d",
    "softId",
    "softMva",
    "softMvaId",
    "charge",
]

# NOTE Charge is not included in the reco columns here, but afterwards
reco_columns = [f"MMuon_{name}" for name in muon_names]