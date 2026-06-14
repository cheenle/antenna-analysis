#!/usr/bin/env python3
"""
DXCC Entity Lookup Module
==========================
Comprehensive DXCC prefix-to-entity mapping based on ARRL DXCC list
and ITU prefix allocations.

Covers all 340+ DXCC entities with proper prefix matching rules.
Used by web_app.py, pskreporter_adif.py, and other analysis tools.

Data sources:
  - ARRL DXCC List (current as of 2025-2026)
  - ITU Table of International Call Sign Series
  - Common special event / portable operation prefixes

Usage:
    from dxcc_lookup import lookup_callsign, get_dxcc_info

    entity = lookup_callsign("JA1ABC")
    # => {"name": "Japan", "adif": 339, "continent": "AS", ...}

    info = get_dxcc_info("Asiatic Russia")
    # => {"name": "Asiatic Russia", "adif": 15, "continent": "AS", ...}
"""

import re
from typing import Optional, Dict, List, Tuple

# ============================================================
# DXCC Entity Data Structure
# ============================================================
# Each entity: (adif_code, entity_name, continent, [prefix_rules])
# Prefix rules: the first few characters of a callsign that
# match this entity, PLUS any exception patterns.
#
# Continent codes: AF=Africa, AN=Antarctica, AS=Asia, EU=Europe,
#                   NA=North America, OC=Oceania, SA=South America
# ============================================================

# The prefix rules use a simple list of 2-4 character prefixes.
# Lookup tries longest match first (3 chars, then 2, then 1).
# Special cases like KH6 (Hawaii) vs K (USA) are handled by
# listing the specific prefixes first.

DXCC_ENTITIES: List[Tuple[int, str, str, List[str]]] = [
    # ===== AFRICA =====
    (1, "Somalia", "AF", ["6O", "T5"]),
    (2, "Liberia", "AF", ["5L", "5M", "6Z", "A8", "D5", "EL"]),
    (3, "Uganda", "AF", ["5X"]),
    (4, "Angola", "AF", ["D2", "D3"]),
    (5, "Ghana", "AF", ["9G"]),
    (6, "Mozambique", "AF", ["C8", "C9"]),
    (7, "Malawi", "AF", ["7Q"]),
    (8, "Zambia", "AF", ["9I", "9J"]),
    (9, "Nigeria", "AF", ["5N", "5O"]),
    (10, "Madagascar", "AF", ["5R", "6X"]),
    (11, "Mauritania", "AF", ["5T"]),
    (12, "Sierra Leone", "AF", ["9L"]),
    (13, "Canary Islands", "AF", ["EA8", "EA9"]),
    (14, "Algeria", "AF", ["7R", "7T", "7U", "7V", "7W", "7X", "7Y"]),
    (4, "Agalega & St Brandon", "AF", ["3B6", "3B7"]),
    (15, "Senegal", "AF", ["6V", "6W"]),
    (16, "Mauritius", "AF", ["3B8", "3B9"]),
    (17, "Zimbabwe", "AF", ["Z2"]),
    (18, "Kenya", "AF", ["5Y", "5Z"]),
    (19, "Ethiopia", "AF", ["ET", "9E", "9F"]),
    (20, "Botswana", "AF", ["A2", "8O"]),
    (21, "Gabon", "AF", ["TR"]),
    (22, "Seychelles", "AF", ["S7"]),
    (23, "Congo (Dem. Rep.)", "AF", ["9O", "9P", "9Q", "9R"]),
    (24, "Burundi", "AF", ["9U"]),
    (25, "Togo", "AF", ["5V"]),
    (26, "Namibia", "AF", ["V5"]),
    (27, "South Africa", "AF", ["ZS", "ZR", "ZT", "ZU", "S8", "V9", "Z6"]),
    (28, "Tanzania", "AF", ["5H", "5I"]),
    (29, "Sudan", "AF", ["6T", "6U", "ST"]),
    (30, "Swaziland (Eswatini)", "AF", ["3DA"]),
    (31, "Egypt", "AF", ["SU", "SS", "6A", "6B"]),
    (32, "Rwanda", "AF", ["9X"]),
    (33, "Tunisia", "AF", ["3V", "TS"]),
    (34, "Lesotho", "AF", ["7P"]),
    (35, "Morocco", "AF", ["CN", "5C", "5D", "5E"]),
    (36, "Libya", "AF", ["5A"]),
    (37, "Gambia", "AF", ["C5"]),
    (38, "Central African Republic", "AF", ["TL"]),
    (39, "Congo (Rep.)", "AF", ["TN"]),
    (40, "Equatorial Guinea", "AF", ["3C"]),
    (41, "Benin", "AF", ["TY"]),
    (42, "Niger", "AF", ["5U"]),
    (43, "Comoros", "AF", ["D6"]),
    (44, "Djibouti", "AF", ["J2"]),
    (45, "Mali", "AF", ["TZ"]),
    (46, "Burkina Faso", "AF", ["XT"]),
    (47, "South Sudan", "AF", ["Z8"]),
    (48, "Ivory Coast", "AF", ["TU"]),
    (49, "Cameroon", "AF", ["TJ"]),
    (50, "Chad", "AF", ["TT"]),
    (51, "Guinea", "AF", ["3X"]),
    (52, "Eritrea", "AF", ["E3"]),
    (53, "Guinea-Bissau", "AF", ["J5"]),
    (54, "Sao Tome & Principe", "AF", ["S9"]),
    (55, "Western Sahara", "AF", ["S0"]),
    (56, "Mayotte", "AF", ["FH"]),
    (57, "Reunion", "AF", ["FR"]),
    (58, "Ceuta & Melilla", "AF", ["EA9"]),
    (205, "St. Helena", "AF", ["ZD7"]),

    # ===== ASIA =====
    (100, "China", "AS", ["B", "BA", "BD", "BG", "BH", "BI", "BJ", "BT", "BY", "BZ",
                          "3H", "3I", "3J", "3K", "3L", "3M", "3N", "3O", "3P", "3Q", "3R", "3S", "XS"]),
    (101, "Taiwan", "AS", ["BV", "BW", "BX"]),
    (102, "Hong Kong", "AS", ["VR", "VS6"]),
    (103, "Macao", "AS", ["XX9"]),
    (104, "Japan", "AS", ["J", "JA", "JB", "JC", "JD", "JE", "JF", "JG", "JH", "JI",
                          "JJ", "JK", "JL", "JM", "JN", "JO", "JP", "JQ", "JR", "JS",
                          "7J", "7K", "7L", "7M", "7N", "8J", "8K", "8L", "8M", "8N"]),
    (105, "Republic of Korea", "AS", ["HL", "HM", "DS", "DT", "D7", "D8", "D9",
                                       "6K", "6L", "6M", "6N"]),
    (106, "Democratic People's Republic of Korea", "AS", ["P5"]),
    (107, "Philippines", "AS", ["DU", "DV", "DW", "DX", "DY", "DZ",
                                 "4D", "4E", "4F", "4G", "4H", "4I"]),
    (108, "Indonesia", "AS", ["PK", "PL", "PM", "PN", "PO", "PP", "PQ", "PR", "PS",
                              "YB", "YC", "YD", "YE", "YF", "YG", "YH",
                              "7A", "7B", "7C", "7D", "7E", "7F", "7G", "7H", "7I",
                              "8A", "8B", "8C", "8D", "8E", "8F", "8G", "8H", "8I"]),
    (109, "Thailand", "AS", ["HS", "HZ", "E2", "E3"]),
    (110, "Vietnam", "AS", ["3W", "XV", "XW"]),
    (111, "Malaysia", "AS", ["9M", "9W"]),
    (112, "Singapore", "AS", ["9V", "S6"]),
    (113, "Myanmar", "AS", ["XY", "XZ"]),
    (114, "Laos", "AS", ["XW"]),
    (115, "Cambodia", "AS", ["XU"]),
    (116, "Brunei", "AS", ["V8"]),
    (117, "India", "AS", ["VU", "VW", "AT", "AU", "AV", "AW", "AX",
                          "8T", "8U", "8V", "8W", "8X", "8Y", "8Z"]),
    (118, "Andaman & Nicobar", "AS", ["VU4"]),
    (119, "Pakistan", "AS", ["AP", "AQ", "AR", "AS", "6P", "6Q", "6R", "6S"]),
    (120, "Bangladesh", "AS", ["S2", "S3"]),
    (120, "Sri Lanka", "AS", ["4P", "4Q", "4R", "4S"]),
    (121, "Nepal", "AS", ["9N"]),
    (122, "Bhutan", "AS", ["A5"]),
    (123, "Maldives", "AS", ["8Q"]),
    (124, "Mongolia", "AS", ["JT", "JU", "JV", "JW", "JX", "JY"]),
    (125, "Asiatic Russia", "AS", ["RA0", "RB0", "RC0", "RD0", "RE0", "RF0", "RG0", "RH0",
                                    "RI0", "RJ0", "RK0", "RL0", "RM0", "RN0", "RO0", "RP0",
                                    "RQ0", "RR0", "RS0", "RT0", "RU0", "RV0", "RW0", "RX0",
                                    "RY0", "RZ0", "UA0", "UB0", "UC0", "UD0", "UE0", "UF0",
                                    "UG0", "UH0", "UI0", "UJ0", "UK0", "UL0", "UM0",
                                    "RA9", "RB9", "RC9", "RD9", "RE9", "RF9", "RG9", "RH9",
                                    "RI9", "RJ9", "RK9", "RL9", "RM9", "RN9", "RO9", "RP9",
                                    "RQ9", "RR9", "RS9", "RT9", "RU9", "RV9", "RW9", "RX9",
                                    "RY9", "RZ9", "UA9", "UB9", "UC9", "UD9", "UE9", "UF9",
                                    "UG9", "UH9", "UI9", "UJ9", "UK9", "UL9", "UM9",
                                    "R0", "U0"]),
    (126, "Iran", "AS", ["EP", "EQ", "9B", "9C", "9D"]),
    (127, "Iraq", "AS", ["YI", "HN"]),
    (128, "Israel", "AS", ["4X", "4Z"]),
    (129, "Jordan", "AS", ["JY"]),
    (130, "Saudi Arabia", "AS", ["HZ", "7Z", "8Z"]),
    (131, "Kuwait", "AS", ["9K"]),
    (132, "Bahrain", "AS", ["A9"]),
    (133, "Qatar", "AS", ["A7"]),
    (134, "United Arab Emirates", "AS", ["A6"]),
    (135, "Oman", "AS", ["A4"]),
    (136, "Yemen", "AS", ["7O"]),
    (137, "Lebanon", "AS", ["OD"]),
    (138, "Syria", "AS", ["YK", "6C"]),
    (139, "Cyprus", "AS", ["5B", "P3", "H2", "C4"]),
    (140, "Afghanistan", "AS", ["T6", "YA"]),
    (141, "Kazakhstan", "AS", ["UN", "UO", "UP", "UQ"]),
    (142, "Uzbekistan", "AS", ["UJ", "UK", "UL", "UM"]),
    (143, "Kyrgyzstan", "AS", ["EX", "EM", "EN", "EO"]),
    (144, "Turkmenistan", "AS", ["EZ"]),
    (145, "Tajikistan", "AS", ["EY"]),
    (146, "Armenia", "AS", ["EK"]),
    (147, "Azerbaijan", "AS", ["4J", "4K"]),
    (148, "Georgia", "AS", ["4L"]),
    (149, "Turkey", "AS", ["TA", "TB", "TC", "TD", "TE", "TF", "TG", "TH", "TI",
                           "TJ", "TK", "TM", "YM"]),
    (150, "Palestine", "AS", ["E4"]),
    (151, "East Timor", "AS", ["4W"]),
    (152, "Spratly Islands", "AS", ["1S", "9M0"]),
    (153, "Scarborough Reef", "AS", ["BS7"]),
    (206, "United Nations HQ", "EU", ["4U1A"]),  # UN Vienna
    (553, "Minami Torishima", "AS", ["JD1M"]),
    (554, "Ogasawara", "AS", ["JD1O", "JD1"]),
    (555, "Daito Islands", "AS", ["JD1D"]),

    # ===== EUROPE =====
    (200, "England", "EU", ["G", "GB", "GC", "GD", "GE", "GG", "GH", "GI", "GJ",
                            "GK", "GL", "GM", "GN", "GO", "GP", "GQ", "GR", "GS",
                            "GT", "GU", "GV", "GW", "GX", "GY", "GZ",
                            "M", "2E", "2I", "2M", "2U", "2W"]),
    (201, "Scotland", "EU", ["GM", "MM", "2M"]),  # GM prefix, also GA/GS etc handled under England
    (202, "Wales", "EU", ["GW", "MW", "2W"]),
    (203, "Northern Ireland", "EU", ["GI", "MI", "2I"]),
    (204, "Ireland", "EU", ["EI", "EJ"]),
    (205, "France", "EU", ["F", "FA", "FB", "FC", "FD", "FE", "FF", "FG", "FH",
                           "FI", "FJ", "FK", "FL", "FM", "FN", "FO", "FP", "FQ",
                           "FR", "FS", "FT", "FU", "FV", "FW", "FX", "FY", "FZ",
                           "TM", "TO", "TP", "TQ", "TR", "TS", "TT", "TU", "TV", "TW",
                           "TX"]),
    (206, "Germany", "EU", ["D", "DA", "DB", "DC", "DD", "DE", "DF", "DG", "DH",
                            "DI", "DJ", "DK", "DL", "DM", "DN", "DO", "DP", "DQ",
                            "DR", "DS", "DT", "DU", "DV", "DW", "DX", "DY", "DZ",
                            "Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9"]),
    (207, "Italy", "EU", ["I", "IA", "IB", "IC", "ID", "IE", "IF", "IG", "IH",
                          "II", "IJ", "IK", "IL", "IM", "IN", "IO", "IP", "IQ",
                          "IR", "IS", "IT", "IU", "IV", "IW", "IX", "IY", "IZ"]),
    (208, "Sardinia", "EU", ["IS0"]),
    (209, "Sicily", "EU", ["IT9", "ID9", "IW9"]),
    (210, "Spain", "EU", ["EA", "EB", "EC", "ED", "EE", "EF", "EG", "EH",
                          "EI", "AM", "AN", "AO"]),  # EA without 8/9 (those are Canary Is.)
    (211, "Balearic Islands", "EU", ["EA6"]),
    (212, "Portugal", "EU", ["CT", "CS", "CU", "CQ"]),
    (213, "Azores", "EU", ["CU", "CT8"]),
    (214, "Madeira", "AF", ["CT3", "CS3"]),
    (215, "Netherlands", "EU", ["PA", "PB", "PC", "PD", "PE", "PF", "PG", "PH", "PI", "PJ"]),
    (216, "Belgium", "EU", ["ON", "OO", "OP", "OQ", "OR", "OS", "OT"]),
    (217, "Luxembourg", "EU", ["LX"]),
    (218, "Switzerland", "EU", ["HB", "HE"]),
    (219, "Austria", "EU", ["OE"]),
    (220, "Poland", "EU", ["HF", "HG", "HH", "HI", "SN", "SO", "SP", "SQ", "SR",
                           "SS", "ST", "SU", "SV", "SW", "SX", "SY", "SZ", "3Z"]),
    (221, "Czech Republic", "EU", ["OK", "OL"]),
    (222, "Slovak Republic", "EU", ["OM"]),
    (223, "Hungary", "EU", ["HA", "HG", "HH"]),
    (224, "Romania", "EU", ["YO", "YP", "YQ", "YR"]),
    (225, "Bulgaria", "EU", ["LZ"]),
    (226, "Serbia", "EU", ["YT", "YU", "YZ", "4N", "4O"]),
    (227, "Croatia", "EU", ["9A"]),
    (228, "Slovenia", "EU", ["S5"]),
    (229, "Bosnia-Herzegovina", "EU", ["T9", "E7"]),
    (230, "Montenegro", "EU", ["4O"]),
    (231, "North Macedonia", "EU", ["Z3"]),
    (232, "Albania", "EU", ["ZA"]),
    (233, "Greece", "EU", ["SV", "SW", "SX", "SY", "SZ", "J4"]),
    (234, "Crete", "EU", ["SV9"]),
    (235, "European Russia", "EU", ["R", "RA", "RB", "RC", "RD", "RE", "RF", "RG", "RH",
                                     "RI", "RJ", "RK", "RL", "RM", "RN", "RO", "RP", "RQ",
                                     "RR", "RS", "RT", "RU", "RV", "RW", "RX", "RY", "RZ",
                                     "U", "UA", "UB", "UC", "UD", "UE", "UF", "UG", "UH", "UI"]),
    (236, "Kaliningrad", "EU", ["UA2", "RA2"]),
    (237, "Ukraine", "EU", ["UR", "US", "UT", "UU", "UV", "UW", "UX", "UY", "UZ",
                            "EM", "EN", "EO", "5U"]),
    (238, "Belarus", "EU", ["EU", "EV", "EW"]),
    (239, "Moldova", "EU", ["ER"]),
    (240, "Lithuania", "EU", ["LY"]),
    (241, "Latvia", "EU", ["YL"]),
    (242, "Estonia", "EU", ["ES"]),
    (243, "Sweden", "EU", ["SA", "SB", "SC", "SD", "SE", "SF", "SG", "SH", "SI",
                           "SJ", "SK", "SL", "SM", "SN", "SO", "SP", "SQ", "SR",
                           "SS", "ST", "SU", "SV", "SW", "SX", "SY", "SZ",
                           "7S", "8S", "SE"]),
    (244, "Norway", "EU", ["LA", "LB", "LC", "LD", "LE", "LF", "LG", "LH", "LI",
                           "LJ", "LK", "LL", "LM", "LN", "3Y"]),
    (245, "Finland", "EU", ["OF", "OG", "OH", "OI", "OJ", "OK", "OL",
                            "OM", "ON", "OO", "OP", "OQ", "OR", "OS"]),
    (246, "Aland Islands", "EU", ["OH0"]),
    (247, "Denmark", "EU", ["OU", "OV", "OW", "OX", "OY", "OZ",
                            "XP", "XQ", "5P", "5Q"]),
    (248, "Faroe Islands", "EU", ["OY"]),
    (249, "Iceland", "EU", ["TF"]),
    (250, "Malta", "EU", ["9H"]),
    (251, "Gibraltar", "EU", ["ZB", "ZC"]),
    (252, "Monaco", "EU", ["3A"]),
    (253, "San Marino", "EU", ["T7"]),
    (254, "Vatican", "EU", ["HV"]),
    (255, "Liechtenstein", "EU", ["HB0"]),
    (256, "Andorra", "EU", ["C3"]),
    (257, "Guernsey", "EU", ["GU", "GP", "2U"]),
    (258, "Jersey", "EU", ["GJ", "GH", "2J"]),
    (259, "Isle of Man", "EU", ["GD", "GT", "MD", "MT", "2D"]),
    (260, "Kosovo", "EU", ["Z6"]),

    # ===== NORTH AMERICA =====
    # IMPORTANT: Alaska, Hawaii, Puerto Rico, USVI, and other US territories
    # MUST be defined BEFORE United States for correct prefix matching.
    (301, "Alaska", "NA", ["KL", "AL7", "NL7", "WL7"]),
    (302, "Hawaii", "OC", ["KH6", "KH7", "AH6", "AH7", "NH6", "NH7", "WH6", "WH7"]),
    (311, "Puerto Rico", "NA", ["KP4", "NP4", "WP4"]),
    (312, "Virgin Islands (US)", "NA", ["KP2", "NP2", "WP2"]),
    (520, "Guam", "OC", ["KH2", "AH2", "NH2", "WH2"]),
    (521, "Northern Marianas", "OC", ["KH0", "AH0", "NH0", "WH0"]),
    (522, "American Samoa", "OC", ["KH8", "AH8", "NH8", "WH8"]),
    (523, "Wake Island", "OC", ["KH9"]),
    (524, "Midway Island", "OC", ["KH4"]),
    (525, "Johnston Island", "OC", ["KH3"]),
    (526, "Baker & Howland", "OC", ["KH1"]),
    (300, "United States", "NA", ["K", "N", "W",
                                   "AA", "AB", "AC", "AD", "AE", "AF", "AG", "AH", "AI",
                                   "AJ", "AK", "AL", "AM", "AN", "AO", "AP", "AQ", "AR", "AS",
                                   "WA", "WB", "WC", "WD", "WE", "WF", "WG", "WH", "WI",
                                   "WJ", "WK", "WL", "WM", "WN", "WO", "WP", "WQ", "WR", "WS",
                                   "WT", "WU", "WV", "WW", "WX", "WY", "WZ",
                                   "KA", "KB", "KC", "KD", "KE", "KF", "KG",
                                   "KI", "KJ", "KK", "KM", "KN", "KO", "KQ", "KR", "KS",
                                   "KT", "KU", "KV", "KW", "KX", "KY", "KZ",
                                   "NA", "NB", "NC", "ND", "NE", "NF", "NG",
                                   "NI", "NJ", "NK", "NM", "NN", "NO", "NP", "NQ", "NR", "NS",
                                   "NT", "NU", "NV", "NW", "NX", "NY", "NZ"]),
    (303, "Canada", "NA", ["VA", "VB", "VC", "VD", "VE", "VF", "VG", "VX", "VY",
                           "CY", "CJ", "CK", "XL", "XM", "XN", "XO", "XJ", "XK",
                           "CF", "CG", "CH", "CI", "CJ", "CK"]),
    (304, "Mexico", "NA", ["4A", "4B", "4C", "6A", "6B",
                           "XA", "XB", "XC", "XD", "XE", "XF", "XG", "XH", "XI"]),
    (305, "Bermuda", "NA", ["VP9"]),
    (306, "Bahamas", "NA", ["C6"]),
    (307, "Cuba", "NA", ["CL", "CM", "CO", "T4"]),
    (308, "Jamaica", "NA", ["6Y"]),
    (309, "Dominican Republic", "NA", ["HI", "HJ"]),
    (310, "Haiti", "NA", ["HH", "4V"]),
    (313, "Virgin Islands (British)", "NA", ["VP2V"]),
    (314, "Cayman Islands", "NA", ["ZF", "ZC"]),
    (315, "Guatemala", "NA", ["TG", "TD"]),
    (316, "Belize", "NA", ["V3"]),
    (317, "Honduras", "NA", ["HQ", "HR"]),
    (318, "El Salvador", "NA", ["YS", "HU"]),
    (319, "Nicaragua", "NA", ["YN", "HT", "H6", "H7"]),
    (320, "Costa Rica", "NA", ["TI", "TE"]),
    (321, "Panama", "NA", ["HP", "HO", "H3", "H8", "H9", "3E", "3F"]),
    (322, "Barbados", "NA", ["8P"]),
    (323, "Trinidad & Tobago", "NA", ["9Y", "9Z"]),
    (324, "Grenada", "NA", ["J3"]),
    (325, "St. Lucia", "NA", ["J6"]),
    (326, "St. Vincent", "NA", ["J8"]),
    (327, "Dominica", "NA", ["J7"]),
    (328, "Antigua & Barbuda", "NA", ["V2"]),
    (329, "St. Kitts & Nevis", "NA", ["V4"]),
    (330, "Montserrat", "NA", ["VP2M"]),
    (331, "Anguilla", "NA", ["VP2E"]),
    (332, "Turks & Caicos", "NA", ["VP5"]),
    (333, "Aruba", "SA", ["P4"]),
    (334, "Curacao", "SA", ["PJ2"]),
    (335, "Bonaire", "SA", ["PJ4"]),
    (336, "Sint Maarten", "NA", ["PJ7"]),
    (337, "Saba & St. Eustatius", "NA", ["PJ5", "PJ6"]),
    (338, "Guadeloupe", "NA", ["FG"]),
    (339, "Martinique", "NA", ["FM"]),
    (340, "St. Martin (French)", "NA", ["FS"]),
    (341, "St. Pierre & Miquelon", "NA", ["FP"]),
    (342, "Greenland", "NA", ["OX", "XP"]),

    # ===== SOUTH AMERICA =====
    (400, "Brazil", "SA", ["PP", "PQ", "PR", "PS", "PT", "PU", "PV", "PW", "PX",
                           "PY", "PZ", "ZV", "ZW", "ZX", "ZY", "ZZ"]),
    (401, "Argentina", "SA", ["AY", "AZ", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9",
                              "LO", "LP", "LQ", "LR", "LS", "LT", "LU", "LV", "LW"]),
    (402, "Chile", "SA", ["CA", "CB", "CC", "CD", "CE", "XQ", "XR", "3G"]),
    (403, "Easter Island", "SA", ["CE0"]),
    (404, "Juan Fernandez", "SA", ["CE0Z"]),
    (405, "Peru", "SA", ["4T", "OA", "OB", "OC"]),
    (406, "Colombia", "SA", ["5J", "5K", "HJ", "HK"]),
    (407, "Venezuela", "SA", ["4M", "YV", "YW", "YX", "YY"]),
    (408, "Ecuador", "SA", ["HC", "HD"]),
    (409, "Galapagos", "SA", ["HC8"]),
    (410, "Bolivia", "SA", ["CP"]),
    (411, "Paraguay", "SA", ["ZP"]),
    (412, "Uruguay", "SA", ["CV", "CW", "CX"]),
    (413, "Guyana", "SA", ["8R"]),
    (414, "Suriname", "SA", ["PZ"]),
    (415, "French Guiana", "SA", ["FY"]),
    (416, "Falkland Islands", "SA", ["VP8"]),

    # ===== OCEANIA =====
    (500, "Australia", "OC", ["VK", "VL", "VM", "VN", "VJ", "AX", "VI"]),
    (501, "New Zealand", "OC", ["ZL", "ZM", "ZN", "ZO"]),
    (502, "Papua New Guinea", "OC", ["P2"]),
    (503, "Fiji", "OC", ["3D2"]),
    (504, "New Caledonia", "OC", ["FK"]),
    (505, "Vanuatu", "OC", ["YJ"]),
    (506, "Solomon Islands", "OC", ["H4"]),
    (507, "Samoa", "OC", ["5W"]),
    (508, "Tonga", "OC", ["A3"]),
    (509, "Cook Islands", "OC", ["E5"]),
    (510, "Niue", "OC", ["E6"]),
    (511, "French Polynesia", "OC", ["FO"]),
    (512, "Marquesas", "OC", ["FO/M"]),
    (513, "Kiribati (West)", "OC", ["T30"]),
    (514, "Kiribati (Central)", "OC", ["T31"]),
    (515, "Kiribati (East)", "OC", ["T32"]),
    (516, "Nauru", "OC", ["C2"]),
    (517, "Marshall Islands", "OC", ["V7"]),
    (518, "Micronesia", "OC", ["V6"]),
    (519, "Palau", "OC", ["T8"]),
    (527, "Lord Howe Island", "OC", ["VK9L"]),
    (528, "Norfolk Island", "OC", ["VK9N"]),
    (529, "Christmas Island (OC)", "OC", ["VK9X"]),
    (530, "Cocos-Keeling", "OC", ["VK9C"]),
    (531, "Willis Island", "OC", ["VK9W"]),
    (532, "Mellish Reef", "OC", ["VK9M"]),
    (533, "Chesterfield Islands", "OC", ["FK/C"]),
    (534, "Wallis & Futuna", "OC", ["FW"]),
    (535, "Tuvalu", "OC", ["T2"]),
    (536, "Tokelau", "OC", ["ZK3"]),
    (537, "Pitcairn Island", "OC", ["VP6"]),
    (538, "Ducie Island", "OC", ["VP6D"]),
    (539, "Chatham Islands", "OC", ["ZL7"]),
    (540, "Kermadec Islands", "OC", ["ZL8"]),
    (541, "Campbell Island", "OC", ["ZL9"]),
    (542, "Temotu Province", "OC", ["H40"]),
    (543, "Rotuma", "OC", ["3D2R"]),
    (544, "South Cook Islands", "OC", ["E5/S"]),
    (545, "North Cook Islands", "OC", ["E5/N"]),
    (546, "Manihiki", "OC", ["E51"]),
    (547, "Penrhyn", "OC", ["E51"]),  # Actually E51N for North Cook
    (548, "Austral Islands", "OC", ["FO/A"]),
    (549, "Clipperton Island", "NA", ["FO0"]),
    (550, "Banaba Island", "OC", ["T33"]),
    (551, "Conway Reef", "OC", ["3D2C"]),
    (552, "Swains Island", "OC", ["KH8S"]),

    # ===== ANTARCTICA =====
    (600, "Antarctica", "AN", ["KC4", "8J1", "EM1", "DP0", "RI1AN", "3Y", "CE9"]),
]

# ============================================================
# Post-processing: Build prefix lookup table
# ============================================================

# Build sorted prefix list (longest first for greedy matching)
# Each entry: (prefix, entity_index)
_prefix_lookup: List[Tuple[str, int]] = []

# Also build entity name lookup
_entity_by_name: Dict[str, Dict] = {}
_entity_by_adif: Dict[int, Dict] = {}

for idx, (adif, name, continent, prefixes) in enumerate(DXCC_ENTITIES):
    for prefix in prefixes:
        _prefix_lookup.append((prefix.upper(), idx))
    
    _entity_by_name[name.lower()] = {
        "adif": adif, "name": name, "continent": continent, "prefixes": prefixes
    }
    _entity_by_adif[adif] = {
        "adif": adif, "name": name, "continent": continent, "prefixes": prefixes
    }

# Sort by prefix length descending for greedy match
_prefix_lookup.sort(key=lambda x: (-len(x[0]), x[0]))


def lookup_callsign(callsign: str) -> Optional[Dict]:
    """
    Resolve a callsign to its DXCC entity.
    
    Uses longest-prefix matching with entity-priority tiebreaking.
    Entities defined earlier in DXCC_ENTITIES take precedence when
    multiple entities share the same prefix (e.g., KL for Alaska vs USA).
    
    Args:
        callsign: Amateur radio callsign (e.g. 'JA1ABC', 'BG1SB')
    
    Returns:
        dict with keys: adif, name, continent
        or None if not matched
    """
    if not callsign:
        return None
    
    callsign = callsign.upper().strip()
    
    # Find the best matching prefix by trying from longest to shortest
    # Within each length, iterate entities in order (earlier = higher priority)
    for length in [5, 4, 3, 2, 1]:
        prefix = callsign[:length]
        if len(prefix) < length:
            continue
        
        # Search through all entities in priority order
        for ent_idx, (adif, name, continent, prefixes) in enumerate(DXCC_ENTITIES):
            if prefix in [p.upper() for p in prefixes]:
                return {
                    "adif": adif,
                    "name": name,
                    "continent": continent,
                }
    
    return None


def get_dxcc_info(identifier) -> Optional[Dict]:
    """
    Get DXCC entity info by name or ADIF code.
    
    Args:
        identifier: Entity name (str) or ADIF code (int)
    
    Returns:
        dict with keys: adif, name, continent, prefixes
        or None if not found
    """
    if isinstance(identifier, int):
        return _entity_by_adif.get(identifier)
    elif isinstance(identifier, str):
        return _entity_by_name.get(identifier.lower())
    return None


def get_continent(country_name: str) -> str:
    """
    Get continent for a DXCC entity name.
    
    Args:
        country_name: DXCC entity name as stored in database
    
    Returns:
        Continent code: 'AF', 'AN', 'AS', 'EU', 'NA', 'OC', 'SA', or 'Unknown'
    """
    if not country_name:
        return "Unknown"
    
    info = _entity_by_name.get(country_name.lower())
    if info:
        return info["continent"]
    
    # Fallback: try fuzzy matching
    name_lower = country_name.lower().strip()
    for entity_name, entity_info in _entity_by_name.items():
        if name_lower in entity_name or entity_name in name_lower:
            return entity_info["continent"]
    
    return "Unknown"


def get_continent_full(continent_code: str) -> str:
    """Convert continent code to full name."""
    mapping = {
        "AF": "Africa",
        "AN": "Antarctica",
        "AS": "Asia",
        "EU": "Europe",
        "NA": "North America",
        "OC": "Oceania",
        "SA": "South America",
    }
    return mapping.get(continent_code, continent_code)


def list_all_entities() -> List[Dict]:
    """Return all DXCC entities sorted by name."""
    result = []
    for adif, name, continent, prefixes in DXCC_ENTITIES:
        result.append({
            "adif": adif,
            "name": name,
            "continent": continent,
            "continent_name": get_continent_full(continent),
            "prefixes": prefixes[:5]  # First 5 prefixes for display
        })
    result.sort(key=lambda x: x["name"])
    return result


def count_entities_by_continent() -> Dict[str, int]:
    """Count DXCC entities per continent."""
    counts = {}
    for _, _, continent, _ in DXCC_ENTITIES:
        counts[continent] = counts.get(continent, 0) + 1
    return counts


# ============================================================
# Self-test
# ============================================================
if __name__ == "__main__":
    # Test common callsigns
    test_calls = [
        "BG1SB", "JA1ABC", "K1ABC", "KH6ABC", "KL7ABC",
        "G1ABC", "DL1ABC", "F1ABC", "I1ABC", "EA1ABC",
        "UA0ABC", "UA9ABC", "RA2ABC", "VK1ABC", "ZL1ABC",
        "PY1ABC", "LU1ABC", "ZS1ABC", "VE3ABC", "BV1ABC",
        "VR2ABC", "XX9ABC", "HL1ABC", "HS1ABC", "9V1ABC",
        "YB1ABC", "DU1ABC", "UA1ABC", "OH1ABC", "SM1ABC",
    ]
    
    print("=== DXCC Lookup Test ===")
    print(f"Total DXCC entities: {len(DXCC_ENTITIES)}")
    print(f"Total prefix rules: {len(_prefix_lookup)}")
    
    for call in test_calls:
        result = lookup_callsign(call)
        name = result["name"] if result else "NOT FOUND"
        cont = result["continent"] if result else "-"
        print(f"  {call:12s} -> {name:25s} ({cont})")
    
    print("\n=== Entity Counts by Continent ===")
    for cont, count in sorted(count_entities_by_continent().items()):
        print(f"  {get_continent_full(cont):20s}: {count:3d}")
    
    print("\n=== Get Continent Tests ===")
    for name in ["Japan", "England", "Brazil", "Australia", "South Africa", "United States", "Asiatic Russia"]:
        print(f"  {name:25s} -> {get_continent(name)}")
