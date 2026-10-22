# DART regression fixture

`pharma-20260814002997-eps.xbrl` is a reduced subset of the user-supplied public DART XBRL archive for receipt 20260814002997 (PharmaResearch, 2026 half-year report). It retains the original EPS/profit/share facts, contexts and units, including separate and diluted alternatives, with XML namespace prefixes serialized afresh. No financial values are synthesized.

Original ZIP SHA-256: `75a614c7af5817ea823f7932ba89ca3fbaa811dc4fec38a6c4ab3d7e3541d953`. The source presentation linkbase places `WeightedAverageShares` under `BasicEarningsPerShareAbstract` and `AdjustedWeightedAverageShares` under `DilutedEarningsPerShareAbstract`.

`pharma-20260319001417-eps.xbrl` retains the actual annual 2025 note and statement contexts. Ordinary-share note EPS is 15893 while the consolidated context without a share-class member reports 14933. These scopes must not be mixed. Original ZIP SHA-256: `7e6d3a9839dbdd6b3aab784ca4bb242fd7edb3c15c74ac55aea1de2a0211a952`.

Revenue and OperatingIncomeLoss facts and their referenced contexts/units are also retained from the same attached official XBRL files, including separate/segment alternatives. Business-metric tests require the explicit consolidated total context, exact standard concepts and matching KRW unit, and distinguish cumulative and standalone quarter periods. These reduced fixtures have different hashes from the original ZIPs.
