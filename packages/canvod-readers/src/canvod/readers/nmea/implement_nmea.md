# Implement NMEA Reader

## Goal

Implement a reader for NMEA sentences

## Instructions

- Make a reader class NmeaObs(GNSSDataReader, BaseModel)
- Use pedantic for validation and parsing
- Implement a method to read NMEA sentences and convert them to xarray.Dataset
- Ensure the dataset has the correct structure with (epoch, sid) dimensions and "File Hash" attribute
- Write tests for the NMEA reader using pytest, including edge cases and invalid input
- Specify erorrs (inherit NmeaError) for invalid NMEA sentences, missing fields, and unsupported sentence types
- create a submodule for NMEA (learn from /gnss_specs/models.py) for Observation, Epoch, Satellite. FIRST TRY TO USE THE MODELS IN /gnss_specs/models.py, if they are not sufficient, then create new models in the nmea submodule.
- You must obey the abstract base class GNSSDataReader, which defines the interface for all GNSS data readers in canvodpy. This includes methods for reading data, validating input, and handling errors. Make sure to implement all required methods and adhere to the expected input/output formats defined by the base class.
- Make sure that reader.to_ds() returns an xarray.Dataset with the correct structure, including (epoch, sid) dimensions and "File Hash" attribute. The dataset should contain the SNR information extracted from the GSV sentences, properly mapped to the corresponding satellite identifiers based on the PRN numbers and constellation information.
- reader.validate_output(ds) contains:
- required_coords = {
            "epoch": "datetime64[ns]",
            "sid": "object",  # string
            "sv": "object",
            "system": "object",
            "band": "object",
            "code": "object",
            "freq_center": "float32",
            "freq_min": "float32",
            "freq_max": "float32",
        }
- Don't make inference from the filename, but use the first encountered RMC or GGA sentence for time and date information. Infer epoch and length of the dataset from the time and date information in the RMC or GGA sentence. If both sentences are present, you can choose either one to extract the time and date information, but make sure to handle cases where one of them might be missing or incomplete.

## GSV reading

The SNR information is contained in the GSV sentences. Each GSV sentence contains information about up to 4 satellites, including their SNR values. To read the SNR information from GSV sentences, you can follow these steps:

1. Parse the NMEA sentences to identify GSV sentences.
2. Get the time and date information from the GGA sentence, which is typically present in the NMEA data. This will be used to create the epoch dimension in the xarray.Dataset. Alternative: Use RMC sentence for time and date information if GGA is not available.
3. Extract the satellite information from each GSV sentence and translate it to the RINEX standard formats defined in /gnss_specs/constellations.py
  - You must translate to the RINEX standard formats defined in /gnss_specs/constellations.py, which include the satellite identifier (sid), constellation/system (system), signal band (band), signal code (code), and frequency information (freq_center, freq_min, freq_max). This translation will require mapping the PRN numbers and constellation information from the GSV sentences to the corresponding identifiers in the RINEX standard.
  - This might be hard, and sometime ambiguous. We might need to match RINEX and NMEA observations to infer the mapping in a later stage. If you face difficulties, in the mapping a-priori, let me know and we make the mapping in a later stage, after we have some RINEX and NMEA observations to compare.

## NMEA parsing

Must be in the data!.
- GGA: Global Positioning System Fix Data (for time and date information) OR RMC: Recommended Minimum Specific GNSS Data (alternative to GGA for time and date information)
- GSV: Satellites in View (for SNR information)

Check each file for the presence of these sentences and handle cases where they may be missing or incomplete. The reader should be robust to variations in the NMEA data format and should provide clear error messages when encountering invalid input.

### Typical NMEA sentence

RMC
```
$GPRMC,001442.00,A,4742.1601213,N,01618.1004213,E,0.0,,010125,5.1,E,D*16
```
| Field | Meaning                                                         |
|-------|-----------------------------------------------------------------|
| 0     | Message ID $--RMC                                               |
|       | Talker ID can be: GP: GPS only, GN: More than one constellation |
| 1     | UTC of position fix                                             |
| 2     | Status A=active or V=void                                       |
| 3     | Latitude                                                        |
| 4     | Longitude                                                       |
| 5     | Speed over the ground in knots                                  |
| 6     | Track angle in degrees (True)                                   |
| 7     | Date                                                            |
| 8     | Magnetic variation, in degrees                                  |
| 9     | The checksum data, always begins with \*                        |

GGA
```
$GPGGA,001442.00,4742.1601213,N,01618.1004213,E,2,40,0.4,708.1584,M,43.2066,M,2.2,0136*4C
```

| Field | Meaning                                                                                                                                                                                                                                     |
|-------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 0     | Message ID \$GPGGA                                                                                                                                                                                                                          |
| 1     | UTC of position fix                                                                                                                                                                                                                         |
| 2     | Latitude                                                                                                                                                                                                                                    |
| 3     | Direction of latitude: N: North, S: South                                                                                                                                                                                                   |
| 4     | Longitude                                                                                                                                                                                                                                   |
| 5     | Direction of longitude: E: East, W: West                                                                                                                                                                                                    |
| 6     | GPS Quality indicator:0: Fix not valid,1: GPS fix,2: Differential GPS fix (DGNSS), SBAS, OmniSTAR VBS, Beacon, RTX in GVBS mode,3: Not applicable,4: RTK Fixed, xFill,5: RTK Float, OmniSTAR XP/HP, Location RTK, RTX,6: INS Dead reckoning |
| 7     | Number of SVs in use, range from00 through to24\+                                                                                                                                                                                           |
| 8     | HDOP                                                                                                                                                                                                                                        |
| 9     | Orthometric height (MSL reference)                                                                                                                                                                                                          |
| 10    | M: unit of measure for orthometric height is meters                                                                                                                                                                                         |
| 11    | Geoid separation                                                                                                                                                                                                                            |
| 12    | M: geoid separation measured in meters                                                                                                                                                                                                      |
| 13    | Age of differential GPS data record, Type1 or Type9. Null field when DGPS is not used.                                                                                                                                                      |
| 14    | Reference station ID, range0000 to4095. A null field when any reference station ID is selected and no corrections are received.                                                                                                             |
| 15    | The checksum data, always begins with \*                                                                                                                                                                                                    |

GSV
```
$GPGSV,6,1,21,02,87,167,50,28,20,094,40,04,15,198,40,31,11,121,39*7A
$GPGSV,6,2,21,08,16,182,40,32,30,049,45,17,31,308,44,03,55,266,48*72
$GPGSV,6,3,21,21,65,131,45,19,07,326,38,10,01,071,37,14,04,273,36*7E
$GPGSV,6,4,21,36,35,170,45,58,13,245,37,40,24,132,35,34,31,208,42*79
$GPGSV,6,5,21,49,34,195,43,57,10,109,36,41,07,108,34,61,03,257,37*7B
$GPGSV,6,6,21*7A
$GLGSV,2,1,08,84,87,059,40,83,22,139,37,70,19,220,36,85,33,322,49*68
$GLGSV,2,2,08,68,39,038,50,69,87,204,52,77,07,021,37,76,06,339,44*68
$GAGSV,3,1,10,11,80,091,44,09,33,186,43,02,10,281,37,19,24,044,37*6C
$GAGSV,3,2,10,12,27,116,37,06,52,164,47,36,45,304,45,10,51,113,46*6B
$GAGSV,3,3,10,04,62,114,47,30,07,330,37*6E
$GBGSV,5,1,18,29,67,267,51,30,40,162,48,22,15,219,,35,16,315,43*6A
$GBGSV,5,2,18,19,18,229,43,05,24,128,38,57,15,090,,39,26,058,42*63
$GBGSV,5,3,18,06,25,073,40,16,26,069,41,09,24,088,39,48,44,226,*63
$GBGSV,5,4,18,32,52,055,49,20,67,222,52,02,08,105,33,31,00,101,*62
$GBGSV,5,5,18,13,05,076,36,60,10,109,38*65
```

| Field | Meaning                                                        |
|-------|----------------------------------------------------------------|
| 0     | Message ID                                                     |
| 1     | Total number of messages of this type in this cycle            |
| 2     | Message number                                                 |
| 3     | Total number of SVs visible                                    |
| 4     | SV PRN number                                                  |
| 5     | Elevation, in degrees, 90° maximum                             |
| 6     | Azimuth, degrees from True North, 000° through 359°            |
| 7     | SNR, 00 through 99 dB (null when not tracking)                 |
| 8–11  | Information about second SV, same format as fields 4 through 7 |
| 12–15 | Information about third SV, same format as fields 4 through 7  |
| 16–19 | Information                                                    |

### Identifying satellites in GSV sentences

To identify the satellites in GSV sentences, you can follow these steps:
- The two-digit prefix in $<XX>GSV sentences indicates the constellation:
  - GP: GPS
  - GL: GLONASS
  - GA: Galileo
  - GB: BeiDou
  - SBAS are included in GP messages
- make a mapping from the satellite PRN numbers in the GSV sentences to the corresponding satellite identifiers in the RINEX standard formats defined in /gnss_specs/constellations.py. This mapping will depend on the specific constellation and the PRN numbering scheme used for that constellation. For example, GPS satellites typically have PRN numbers ranging from 1 to 32, while GLONASS satellites have PRN numbers that can be higher. You will need to refer to the documentation for each constellation to determine the correct mapping.

### PRN

crawl: /nmea/NMEA Revealed.html

Generally:
GPS satellites are identified by their PRN numbers, which range from 1 to 32.

The numbers 33-64 are reserved for WAAS satellites. The WAAS system PRN numbers are 120-138. The offset from NMEA WAAS SV ID to WAAS PRN number is 87. A WAAS PRN number of 120 minus 87 yields the SV ID of 33. The addition of 87 to the SV ID yields the WAAS PRN number.

The numbers 65-96 are reserved for GLONASS satellites. GLONASS satellites are identified by 64+satellite slot number. The slot numbers are 1 through 24 for the full constellation of 24 satellites, this gives a range of 65 through 88. The numbers 89 through 96 are available if slot numbers above 24 are allocated to on-orbit spares.

| PRN Range | Constellation/System                                  |
|-----------|-------------------------------------------------------|
| 1-32      | GPS                                                   |
| 33-54     | Various SBAS systems (EGNOS, WAAS, SDCM, GAGAN, MSAS) |
| 55-64     | Not used (might be assigned to further SBAS systems)  |
| 65-88     | GLONASS                                               |
| 89-96     | GLONASS (future extensions?)                          |
| 97-119    | Not used                                              |
| 120-151   | Not used (SBAS PRNs occupy this range)                |
| 152-158   | Various SBAS systems (EGNOS, WAAS, SDCM, GAGAN, MSAS) |
| 159-172   | Not used                                              |
| 173-182   | IMES                                                  |
| 193-197   | QZSS                                                  |
| 196-200   | QZSS (future extensions?)                             |
| 201-235   | BeiDou (u-blox, not NMEA)                             |
| 301-336   | GALILEO                                               |
| 401-437   | BeiDou (NMEA)                                         |

GLONASS satellite numbers come in two flavors. If a sentence has a GL talker ID, expect the skyviews to be GLONASS-only and in the range 1-32; you must add 64 to get a globally-unique NMEA ID. If the sentence has a GN talker ID, the device emits a multi-constellation skyview with GLONASS IDs already in the 65-96 range.

QZSS is a geosynchronous (not geostationary) system of three (possibly four) satellites in highly elliptical, inclined, orbits. It is designed to provide coverage in Japan’s urban canyons.

BeiDou-1 consists of 4 geostationary satellites operated by China, operational since 2004. Coverage area is the Chinese mainland. gpsd does not support this, as this requires special hardware, and prior arrangements with the operator, who calculates and returns the position fix.

BeiDou-2 (earlier known as COMPASS) is a system of 35 satellites, including 5 geostationary for compatibility with BeiDou-1. As of late 2015, coverage is complete over most of Asia and the West Pacific. It is expected to be fully operational by 2020, by when coverage area is expected to be worldwide.

Note that the PRN system is becoming increasingly fragmented and unworkable. New GPS denote each satellite, and their signals, by their constellation (gnssID), satellite id in that constellation (svId), and signal type (sigId). NMEA, as of version 4, has not adapted.

| GNSS System         | System ID | Satellite ID    | Signal ID | Signal Channel |
|---------------------|-----------|-----------------|-----------|----------------|
| GPS                 | 1 (GP)    | 1 -99           | 0         | All signals    |
| GPS                 | 1 (GP)    | 1 -32 GPS       | 1         | L1 C/A         |
| GPS                 | 1 (GP)    | 33 -64 GPS SBAS | 2         | L1 P(Y)        |
| GPS                 | 1 (GP)    | 1 -99           | 3         | L1 M           |
| GPS                 | 1 (GP)    | 1 -99           | 4         | L2 P(Y)        |
| GPS                 | 1 (GP)    | 1 -99           | 5         | L2C-M          |
| GPS                 | 1 (GP)    | 1 -99           | 6         | L2C-L          |
| GPS                 | 1 (GP)    | 1 -99           | 7         | L5-I           |
| GPS                 | 1 (GP)    | 1 -99           | 8         | L5-Q           |
| GPS                 | 1 (GP)    | 1 -99           | 9 - F     | Reserved       |
| GLONASS             | 2 (GL)    | 1 -99           | 0         | All signals    |
| GLONASS             | 2 (GL)    | 33 -64 SBAS     | 1         | L1 C/A         |
| GLONASS             | 2 (GL)    | 65 -99 GL       | 2         | L1 P           |
| GLONASS             | 2 (GL)    | 1 -99           | 3         | L2 C/A         |
| GLONASS             | 2 (GL)    | 1 -99           | 4         | L2 P           |
| GLONASS             | 2 (GL)    | 1 -99           | 5 -16     | Reserved       |
| Galileo             | 3 (GA)    | 1 -99           | 0         | All signals    |
| Galileo             | 3 (GA)    | 1 -36 GA        | 1         | E5a            |
| Galileo             | 3 (GA)    | 37 -64 GA SBAS  | 2         | E5b            |
| Galileo             | 3 (GA)    | 1 -99           | 3         | E5a+b          |
| Galileo             | 3 (GA)    | 1 -99           | 4         | E6-A           |
| Galileo             | 3 (GA)    | 1 -99           | 5         | E6-BC          |
| Galileo             | 3 (GA)    | 1 -99           | 6         | L1-A           |
| Galileo             | 3 (GA)    | 1 -99           | 7         | L1-BC          |
| Galileo             | 3 (GA)    | 1 -99           | 8 -16     | Reserved       |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 0         | All signals    |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -64 BD        | 1         | B1I            |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 2         | B1Q            |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 3         | B1C            |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 4         | B1A            |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 5         | B2-a           |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 6         | B2-b           |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 7         | B2 a+b         |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 8         | B3I            |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 9         | B3Q            |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 10        | B3A            |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 11        | B2I            |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 12        | B2Q            |
| BDS (BeiDou System) | 4 (GB/BD) | 1 -99           | 13 -16    | Reserved       |
| QZSS                | 5 (GQ)    | 1 -99           | 0         | All signals    |
| QZSS                | 5 (GQ)    | 1 -10 QZ        | 1         | L1 C/A         |
| QZSS                | 5 (GQ)    | 55 -63 QZ SBAS  | 2         | L1C (D)        |
| QZSS                | 5 (GQ)    | 1 -99           | 3         | L1C (P)        |
| QZSS                | 5 (GQ)    | 1 -99           | 4         | LIS            |
| QZSS                | 5 (GQ)    | 1 -99           | 5         | L2C-M          |
| QZSS                | 5 (GQ)    | 1 -99           | 6         | L2C-L          |
| QZSS                | 5 (GQ)    | 1 -99           | 7         | L5-I           |
| QZSS                | 5 (GQ)    | 1 -99           | 8         | L5-Q           |
| QZSS                | 5 (GQ)    | 1 -99           | 9         | L6D            |
| QZSS                | 5 (GQ)    | 1 -99           | 10        | L6E            |
| QZSS                | 5 (GQ)    | 1 -99           | 11 -16    | Reserved       |
| NavIC               | 6 (GI)    | 1 -99           | 0         | All signals    |
| NavIC               | 6 (GI)    | 1 -15 GI        | 1         | L5-SPS         |
| NavIC               | 6 (GI)    | 33 -64 SBAS     | 2         | S-SPS          |
| NavIC               | 6 (GI)    | 1 -99           | 3         | L5-RS          |
| NavIC               | 6 (GI)    | 1 -99           | 4         | S-RS           |
| NavIC               | 6 (GI)    | 1 -99           | 5         | L1-SPS         |
| NavIC               | 6 (GI)    | 1 -99           | 6 - F     | Reserved       |
