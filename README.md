# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/TUW-GEO/canvodpy/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                            |    Stmts |     Miss |   Cover |   Missing |
|-------------------------------------------------------------------------------- | -------: | -------: | ------: | --------: |
| canvodpy/src/canvodpy/\_\_init\_\_.py                                           |       66 |       14 |     79% |266-267, 273-274, 280-281, 288-289, 295-296, 302-303, 309-310 |
| canvodpy/src/canvodpy/\_deprecation.py                                          |       21 |        2 |     90% |     32-33 |
| canvodpy/src/canvodpy/api.py                                                    |      141 |       67 |     52% |109, 114-118, 123, 128, 191, 206-208, 211, 309-316, 374, 377, 380, 408-425, 457-462, 495-551, 581, 584, 648-654, 710-715, 745-746 |
| canvodpy/src/canvodpy/cli/\_\_init\_\_.py                                       |        0 |        0 |    100% |           |
| canvodpy/src/canvodpy/cli/app.py                                                |       33 |        4 |     88% |54-55, 76, 80 |
| canvodpy/src/canvodpy/cli/config.py                                             |      323 |      163 |     50% |63-66, 184-190, 205, 216, 308-309, 323, 342-378, 404, 407-410, 441-465, 483-493, 508-581, 596-680, 695-703 |
| canvodpy/src/canvodpy/cli/dashboard.py                                          |      129 |      129 |      0% |    24-296 |
| canvodpy/src/canvodpy/cli/dashboards/\_\_init\_\_.py                            |        0 |        0 |    100% |           |
| canvodpy/src/canvodpy/cli/dashboards/performance.py                             |      126 |      126 |      0% |     1-336 |
| canvodpy/src/canvodpy/cli/doctor.py                                             |       68 |       10 |     85% |32, 38-39, 45-46, 102-105, 124-128 |
| canvodpy/src/canvodpy/cli/perf\_dashboard.py                                    |       20 |       11 |     45% |     52-63 |
| canvodpy/src/canvodpy/cli/run.py                                                |      264 |      224 |     15% |65-67, 79-104, 133-176, 180-181, 190-198, 204-222, 258-337, 341-659, 763-778, 782 |
| canvodpy/src/canvodpy/cli/stats.py                                              |      109 |       94 |     14% |37-72, 88-146, 159-190 |
| canvodpy/src/canvodpy/cli/store.py                                              |      188 |       33 |     82% |54-55, 76-77, 152-153, 158, 189-192, 244-247, 273, 357, 382-386, 389, 433-439, 452-455, 457-465, 477-487 |
| canvodpy/src/canvodpy/cli/vod.py                                                |       56 |       46 |     18% |22-26, 55-77, 116-155, 159 |
| canvodpy/src/canvodpy/diagnostics/\_\_init\_\_.py                               |        2 |        2 |      0% |       7-9 |
| canvodpy/src/canvodpy/diagnostics/sbf\_timing\_diagnostics\_new\_api.py         |      100 |      100 |      0% |    13-229 |
| canvodpy/src/canvodpy/diagnostics/timing\_diagnostics\_new\_api.py              |      100 |      100 |      0% |    13-233 |
| canvodpy/src/canvodpy/diagnostics/timing\_diagnostics\_script.py                |      101 |      101 |      0% |     9-237 |
| canvodpy/src/canvodpy/factories.py                                              |      114 |       51 |     55% |236-259, 275-309, 320-331 |
| canvodpy/src/canvodpy/fluent.py                                                 |      192 |      132 |     31% |60-86, 177-179, 205-253, 268-334, 345-357, 379-417, 431-441, 454-465, 478-480, 485-493, 498-501 |
| canvodpy/src/canvodpy/functional.py                                             |       83 |        0 |    100% |           |
| canvodpy/src/canvodpy/globals.py                                                |        9 |        9 |      0% |      8-50 |
| canvodpy/src/canvodpy/logging/\_\_init\_\_.py                                   |        8 |        0 |    100% |           |
| canvodpy/src/canvodpy/logging/context.py                                        |       11 |       11 |      0% |      3-37 |
| canvodpy/src/canvodpy/logging/logging\_config.py                                |      175 |       13 |     93% |48, 99, 145, 159, 225, 282-284, 533-538 |
| canvodpy/src/canvodpy/logging/run\_context.py                                   |        8 |        0 |    100% |           |
| canvodpy/src/canvodpy/logging/stage\_timer.py                                   |       54 |        1 |     98% |       149 |
| canvodpy/src/canvodpy/orchestrator/\_\_init\_\_.py                              |       14 |        7 |     50% |     38-46 |
| canvodpy/src/canvodpy/orchestrator/interpolator.py                              |      133 |        8 |     94% |177, 200-203, 340-342, 348-354 |
| canvodpy/src/canvodpy/orchestrator/matcher.py                                   |       48 |        8 |     83% |    95-103 |
| canvodpy/src/canvodpy/orchestrator/pipeline.py                                  |      503 |      376 |     25% |37-39, 249-293, 304, 307, 310, 335-360, 378-432, 495-512, 579-669, 688, 712-719, 749-756, 787-1282, 1311-1341, 1383-1390, 1403-1422, 1438-1470, 1479-1503 |
| canvodpy/src/canvodpy/orchestrator/processor.py                                 |     1659 |     1158 |     30% |83-85, 90, 200-254, 266-268, 290-295, 316, 378-386, 475-477, 496-501, 521, 582-590, 634-657, 667-674, 684-692, 714-739, 759-778, 794-814, 906-972, 988-1038, 1051-1054, 1091, 1137-1138, 1250-1274, 1335-1384, 1414-1463, 1467-1473, 1504-1534, 1546-1571, 1584-1613, 1627-1639, 1677-1743, 1803, 1891-1894, 1927-2049, 2080, 2096, 2136-2203, 2233, 2285-2295, 2380-2381, 2408-2409, 2415-2423, 2436-2443, 2462-2463, 2569, 2644-2649, 2809, 2849, 2852, 2874, 2903-2904, 2923-2972, 2988-3006, 3033-3641, 3657-3672, 3709-3840, 3879-4144, 4183-4537, 4560-4589, 4612-4713, 4716, 4750, 4753, 4769-4879, 4911-5041, 5045-5110 |
| canvodpy/src/canvodpy/orchestrator/resources.py                                 |       92 |       51 |     45% |79-82, 86-91, 95-98, 104-154, 198-199, 225-226 |
| canvodpy/src/canvodpy/orchestrator/store\_retry.py                              |       14 |        7 |     50% |     41-53 |
| canvodpy/src/canvodpy/orchestrator/vod\_reconcile.py                            |       53 |        0 |    100% |           |
| canvodpy/src/canvodpy/utils/\_\_init\_\_.py                                     |        0 |        0 |    100% |           |
| canvodpy/src/canvodpy/vod\_computer.py                                          |      138 |       66 |     52% |62-120, 183-198, 229-275, 398-401, 435-436 |
| canvodpy/src/canvodpy/workflow.py                                               |       96 |       25 |     74% |147-149, 236-238, 300-302, 359-381, 472-479 |
| canvodpy/src/canvodpy/workflows/\_\_init\_\_.py                                 |        2 |        0 |    100% |           |
| canvodpy/src/canvodpy/workflows/tasks.py                                        |      520 |      340 |     35% |49-60, 70-73, 160-184, 343-352, 365-430, 473-582, 610-634, 685-783, 823-943, 997-1139, 1258-1261, 1309-1364, 1407-1408 |
| packages/canvod-auxiliary/src/canvod/auxiliary/\_\_init\_\_.py                  |       27 |        4 |     85% |125-126, 148-149 |
| packages/canvod-auxiliary/src/canvod/auxiliary/\_internal/\_\_init\_\_.py       |        4 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/\_internal/logger.py             |        5 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/\_internal/units.py              |        5 |        1 |     80% |        16 |
| packages/canvod-auxiliary/src/canvod/auxiliary/augmentation.py                  |      205 |      114 |     44% |157, 168, 395-435, 450-470, 496-514, 536-588, 593-641, 649-653, 708-753, 758-778 |
| packages/canvod-auxiliary/src/canvod/auxiliary/cache\_fingerprint.py            |        8 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/clock/\_\_init\_\_.py            |        4 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/clock/parser.py                  |       48 |       41 |     15% |39-53, 82-128, 146-153 |
| packages/canvod-auxiliary/src/canvod/auxiliary/clock/reader.py                  |       51 |       30 |     41% |67-70, 74-78, 97-102, 118-135, 150-172, 189-212 |
| packages/canvod-auxiliary/src/canvod/auxiliary/clock/validator.py               |       32 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/container.py                     |       10 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/core/\_\_init\_\_.py             |        3 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/core/base.py                     |      112 |       76 |     32% |58-68, 102-103, 133-141, 173-175, 213-288, 304, 309, 314-318, 328-335, 340, 345 |
| packages/canvod-auxiliary/src/canvod/auxiliary/core/downloader.py               |      159 |      131 |     18% |30, 65, 69, 93-115, 139-241, 247-270, 274-333, 349-380, 384-386, 390-392 |
| packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/\_\_init\_\_.py        |        5 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/parser.py              |       78 |       67 |     14% |28-29, 46-134, 154-155, 184-197, 201 |
| packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/provider.py            |      106 |       89 |     16% |119-125, 149-226, 252-301, 326-327, 335, 361-418 |
| packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/reader.py              |       84 |       60 |     29% |64-71, 75-79, 88-96, 112-132, 150-168, 172-187, 206-247, 254-261 |
| packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/validator.py           |       36 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/interpolation/\_\_init\_\_.py    |        2 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/interpolation/interpolator.py    |      128 |       53 |     59% |26, 89, 93, 122, 130-196, 230-246, 309, 371, 376, 396, 428-438 |
| packages/canvod-auxiliary/src/canvod/auxiliary/matching/\_\_init\_\_.py         |        2 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/matching/dataset\_matcher.py     |       38 |       28 |     26% |95-102, 128-135, 152-153, 172-173, 193-194, 222-251 |
| packages/canvod-auxiliary/src/canvod/auxiliary/pipeline.py                      |      118 |        8 |     93% |254, 263, 318-331, 440 |
| packages/canvod-auxiliary/src/canvod/auxiliary/position/\_\_init\_\_.py         |        3 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/position/position.py             |       50 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/position/spherical\_coords.py    |       29 |        3 |     90% |   184-196 |
| packages/canvod-auxiliary/src/canvod/auxiliary/preprocessing.py                 |      165 |       53 |     68% |165, 169-177, 183, 244, 286-361 |
| packages/canvod-auxiliary/src/canvod/auxiliary/products/\_\_init\_\_.py         |        3 |        0 |    100% |           |
| packages/canvod-auxiliary/src/canvod/auxiliary/products/models.py               |      103 |       19 |     82% |109, 167-176, 192-206 |
| packages/canvod-auxiliary/src/canvod/auxiliary/products/registry\_config.py     |       79 |        8 |     90% |29, 77, 112, 196-197, 205, 251, 256 |
| packages/canvod-config/src/canvod/config/\_\_init\_\_.py                        |        3 |        0 |    100% |           |
| packages/canvod-config/src/canvod/config/loader.py                              |      122 |       15 |     88% |93-104, 203-204, 251-252, 266, 271 |
| packages/canvod-config/src/canvod/config/models/\_\_init\_\_.py                 |       14 |        0 |    100% |           |
| packages/canvod-config/src/canvod/config/models/aux\_data.py                    |       14 |        0 |    100% |           |
| packages/canvod-config/src/canvod/config/models/base.py                         |        3 |        0 |    100% |           |
| packages/canvod-config/src/canvod/config/models/compression.py                  |       31 |        0 |    100% |           |
| packages/canvod-config/src/canvod/config/models/logging.py                      |       17 |        7 |     59% | 46-54, 64 |
| packages/canvod-config/src/canvod/config/models/metadata.py                     |       40 |        0 |    100% |           |
| packages/canvod-config/src/canvod/config/models/preprocessing.py                |       26 |        0 |    100% |           |
| packages/canvod-config/src/canvod/config/models/processing.py                   |       32 |        6 |     81% |46-53, 58-65 |
| packages/canvod-config/src/canvod/config/models/processing\_params.py           |       39 |        0 |    100% |           |
| packages/canvod-config/src/canvod/config/models/references.py                   |       18 |        0 |    100% |           |
| packages/canvod-config/src/canvod/config/models/root.py                         |       16 |        0 |    100% |           |
| packages/canvod-config/src/canvod/config/models/sids.py                         |       37 |        3 |     92% |     81-83 |
| packages/canvod-config/src/canvod/config/models/sites.py                        |      106 |        4 |     96% |   203-206 |
| packages/canvod-config/src/canvod/config/models/storage.py                      |       56 |        6 |     89% |216, 277, 318-321 |
| packages/canvod-grids/src/canvod/grids/\_\_init\_\_.py                          |       26 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/\_internal/\_\_init\_\_.py               |        3 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/\_internal/geometry.py                   |       14 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/\_internal/logger.py                     |        5 |        1 |     80% |        26 |
| packages/canvod-grids/src/canvod/grids/aggregation.py                           |      198 |      123 |     38% |230-352, 470, 481, 497-501, 509-521, 530-547, 560-623, 635-647, 664-681 |
| packages/canvod-grids/src/canvod/grids/analysis/\_\_init\_\_.py                 |       16 |        2 |     88% |   126-130 |
| packages/canvod-grids/src/canvod/grids/analysis/filtering.py                    |      215 |      130 |     40% |133, 156-172, 180, 203-224, 232, 258-265, 273, 299-304, 330-331, 339, 384, 413, 479-481, 500-512, 535-658, 662-667, 682, 693 |
| packages/canvod-grids/src/canvod/grids/analysis/hampel\_filtering.py            |      186 |      170 |      9% |81-121, 179-342, 367-375, 406-435, 485-660 |
| packages/canvod-grids/src/canvod/grids/analysis/masking.py                      |      132 |      111 |     16% |58-60, 91-109, 136-144, 172-183, 199-203, 219-223, 254-269, 296-303, 342-359, 396-410, 438-452, 463-489, 500-501, 512-513, 545-560, 583-585 |
| packages/canvod-grids/src/canvod/grids/analysis/per\_cell\_analysis.py          |      277 |      247 |     11% |84-92, 100-104, 117-135, 142-171, 180-212, 225-243, 252-263, 267-284, 292-307, 317-336, 342-355, 371-410, 441-458, 479-481, 509-520, 538-539, 566-599, 616-622, 646 |
| packages/canvod-grids/src/canvod/grids/analysis/per\_cell\_filtering.py         |      150 |      119 |     21% |56, 112-152, 180-226, 243, 266-280, 291, 314-324, 335, 361-366, 377, 403-410, 441-443, 466-478, 499-539, 555, 572 |
| packages/canvod-grids/src/canvod/grids/analysis/sigma\_clip\_filter.py          |      152 |      136 |     11% |92-123, 167-204, 264-391, 438-526 |
| packages/canvod-grids/src/canvod/grids/analysis/solar.py                        |      146 |      123 |     16% |83-100, 124-129, 135-149, 158-249, 254-269, 291-292, 316-317, 353-413, 442-445, 465-477, 490-491, 522-524, 554-558 |
| packages/canvod-grids/src/canvod/grids/analysis/spatial.py                      |       65 |       53 |     18% |80-94, 139-201, 239-270 |
| packages/canvod-grids/src/canvod/grids/analysis/temporal.py                     |      311 |      289 |      7% |105-128, 173-207, 264-325, 336-349, 368-442, 478-573, 613-706, 732-756, 793-864, 891-919, 946-993 |
| packages/canvod-grids/src/canvod/grids/analysis/weighting.py                    |      232 |      202 |     13% |73-77, 116-140, 168-191, 206-217, 233-239, 250-252, 263, 274-284, 300-317, 321-327, 340-378, 389-414, 435-465, 486-517, 524-525, 549-574, 589-596, 621-636, 641-646, 668, 687-689 |
| packages/canvod-grids/src/canvod/grids/core/\_\_init\_\_.py                     |        4 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/core/grid\_builder.py                    |       42 |        2 |     95% |  112, 155 |
| packages/canvod-grids/src/canvod/grids/core/grid\_data.py                       |      119 |       15 |     87% |94-95, 143, 170, 177-178, 245-254 |
| packages/canvod-grids/src/canvod/grids/core/grid\_types.py                      |        9 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/grids\_impl/\_\_init\_\_.py              |        8 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/grids\_impl/equal\_angle\_grid.py        |       33 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/grids\_impl/equal\_area\_grid.py         |       43 |        1 |     98% |       177 |
| packages/canvod-grids/src/canvod/grids/grids\_impl/equirectangular\_grid.py     |       25 |        1 |     96% |       106 |
| packages/canvod-grids/src/canvod/grids/grids\_impl/fibonacci\_grid.py           |       60 |        6 |     90% |137-139, 203-204, 212 |
| packages/canvod-grids/src/canvod/grids/grids\_impl/geodesic\_grid.py            |       90 |        2 |     98% |  147, 268 |
| packages/canvod-grids/src/canvod/grids/grids\_impl/healpix\_grid.py             |       46 |        7 |     85% |122-123, 126, 134-135, 211, 247 |
| packages/canvod-grids/src/canvod/grids/grids\_impl/htm\_grid.py                 |       76 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/operations.py                            |      334 |      126 |     62% |209-239, 319-320, 369, 432-451, 458-478, 490-511, 574, 579-624, 754-771, 824 |
| packages/canvod-grids/src/canvod/grids/workflows/\_\_init\_\_.py                |        2 |        0 |    100% |           |
| packages/canvod-grids/src/canvod/grids/workflows/adapted\_workflow.py           |      188 |      164 |     13% |45-52, 71-73, 105-106, 132-136, 173-227, 277, 334-391, 427-490, 498-509, 518-530, 545-565, 618-697, 718, 737-765 |
| packages/canvod-ops/src/canvod/ops/\_\_init\_\_.py                              |        6 |        0 |    100% |           |
| packages/canvod-ops/src/canvod/ops/base.py                                      |       10 |        0 |    100% |           |
| packages/canvod-ops/src/canvod/ops/grid.py                                      |       56 |        0 |    100% |           |
| packages/canvod-ops/src/canvod/ops/pipeline.py                                  |       30 |        0 |    100% |           |
| packages/canvod-ops/src/canvod/ops/registry.py                                  |       18 |        5 |     72% |     29-34 |
| packages/canvod-ops/src/canvod/ops/temporal.py                                  |      111 |        3 |     97% |     27-29 |
| packages/canvod-preflight/src/canvod/preflight/\_\_init\_\_.py                  |        7 |        0 |    100% |           |
| packages/canvod-preflight/src/canvod/preflight/config\_models.py                |       23 |        0 |    100% |           |
| packages/canvod-preflight/src/canvod/preflight/convention.py                    |       73 |        0 |    100% |           |
| packages/canvod-preflight/src/canvod/preflight/mapping.py                       |      182 |       18 |     90% |74-77, 136-138, 169-171, 196-198, 209, 215, 222, 238, 326 |
| packages/canvod-preflight/src/canvod/preflight/patterns.py                      |       45 |        0 |    100% |           |
| packages/canvod-preflight/src/canvod/preflight/validator.py                     |       81 |       18 |     78% |53, 110, 120-121, 129, 153-157, 167, 176-183, 197 |
| packages/canvod-readers/src/canvod/readers/\_\_init\_\_.py                      |       10 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/base.py                              |      149 |       33 |     78% |97, 102, 115, 159, 163-165, 169-180, 186-193, 200-202, 255, 335, 405, 474, 489 |
| packages/canvod-readers/src/canvod/readers/builder.py                           |       64 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/\_\_init\_\_.py          |        2 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/bands.py                 |      127 |       98 |     23% |166-416, 420-426 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/constants.py             |       13 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/constellations.py        |      110 |       13 |     88% |76-94, 433-434, 659-661 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/exceptions.py            |       20 |        3 |     85% |59, 105, 167 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/metadata.py              |       24 |        9 |     62% |264, 268-279 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/models.py                |      271 |       54 |     80% |90-91, 93-94, 272-278, 358, 435-443, 469-478, 500-523, 636-641, 735-736, 797-798, 806-809, 817-820, 827, 833-834, 868, 871, 874-882, 910 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/satellite\_catalog.py    |      371 |       55 |     85% |317, 326-329, 333-338, 354-358, 378-379, 391-404, 409-424, 453, 552, 572, 674, 741-747, 800, 820, 827, 837, 845, 861, 869, 885, 893, 909, 918, 937 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/signals.py               |       23 |        1 |     96% |       114 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/utils.py                 |       20 |        2 |     90% |     25-26 |
| packages/canvod-readers/src/canvod/readers/gnss\_specs/validation\_constants.py |       32 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/matching/\_\_init\_\_.py             |        3 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/matching/dir\_matcher.py             |      113 |       10 |     91% |49-52, 345-346, 366, 371, 384-385 |
| packages/canvod-readers/src/canvod/readers/matching/models.py                   |        7 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/nmea/\_\_init\_\_.py                 |        2 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/nmea/exceptions.py                   |       10 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/nmea/v4\_00.py                       |      340 |      134 |     61% |67-68, 92, 165, 173, 178, 185, 239-240, 245-254, 306-307, 311-313, 317-318, 347-348, 378-379, 390-393, 399, 403, 407, 411, 415-419, 423, 427-431, 437, 460-568, 596, 601-602, 619, 639-661, 670-678 |
| packages/canvod-readers/src/canvod/readers/rinex/\_\_init\_\_.py                |        4 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/rinex/v2\_11.py                      |      657 |      536 |     18% |104-106, 125-129, 190-192, 202-210, 218-401, 406, 409, 415-416, 432-455, 460-463, 522-532, 592-597, 601, 604, 612, 618-633, 637, 643, 647-661, 665-667, 671, 675-679, 701-740, 767-779, 789-818, 836-873, 884-959, 978, 992-1001, 1005, 1009-1027, 1043-1284, 1317-1372, 1380-1396, 1401-1406, 1409-1452, 1482-1504, 1537 |
| packages/canvod-readers/src/canvod/readers/rinex/v3\_04.py                      |      748 |      613 |     18% |91-94, 117, 125-149, 212-219, 227-237, 259-404, 414-444, 461-466, 485-494, 511-518, 537-568, 587-595, 614-627, 646-678, 697-706, 711, 715, 723-724, 794-816, 828, 832, 841, 852-859, 871, 883, 895-900, 912-914, 926, 938-942, 960-974, 996-1071, 1079-1122, 1134, 1150-1170, 1197-1200, 1219, 1246-1257, 1264-1281, 1292-1306, 1324-1347, 1376-1403, 1429-1446, 1466-1531, 1548-1778, 1803-1808, 1841-1890, 1929-1955, 1958-2003, 2018-2019 |
| packages/canvod-readers/src/canvod/readers/rinex/v3\_05\_stripped.py            |      136 |      119 |     12% |55, 59-69, 74-217, 224-266 |
| packages/canvod-readers/src/canvod/readers/sbf/\_\_init\_\_.py                  |        3 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/sbf/\_registry.py                    |       41 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/sbf/\_scaling.py                     |      106 |       27 |     75% |442-444, 449-452, 457-459, 469-471, 476-478, 489-491, 496-503 |
| packages/canvod-readers/src/canvod/readers/sbf/models.py                        |       46 |        0 |    100% |           |
| packages/canvod-readers/src/canvod/readers/sbf/reader.py                        |     1032 |      924 |     10% |71-72, 114-116, 130-135, 145, 193-204, 898-910, 933-954, 971-986, 998-1027, 1079, 1097-1107, 1122-1123, 1139-1141, 1157-1162, 1173, 1186, 1211-1216, 1236-1258, 1284-1306, 1345-1548, 1576-2063, 2104-2935, 2963-2996, 3028-3037, 3060-3099, 3139-3169, 3187 |
| packages/canvod-store-metadata/src/canvod/store\_metadata/\_\_init\_\_.py       |        7 |        0 |    100% |           |
| packages/canvod-store-metadata/src/canvod/store\_metadata/collectors.py         |      133 |       24 |     82% |60-61, 81-83, 92-102, 108, 116, 131-132, 181, 185, 188, 192, 262 |
| packages/canvod-store-metadata/src/canvod/store\_metadata/inventory.py          |       93 |       31 |     67% |67, 129-132, 147, 150-151, 179, 240, 242, 244, 323-347 |
| packages/canvod-store-metadata/src/canvod/store\_metadata/io.py                 |       55 |        4 |     93% |38-39, 95-96 |
| packages/canvod-store-metadata/src/canvod/store\_metadata/schema.py             |      143 |        0 |    100% |           |
| packages/canvod-store-metadata/src/canvod/store\_metadata/show.py               |      255 |      225 |     12% |24, 28-29, 33-39, 43-52, 56-66, 70-80, 84-91, 95-103, 107-123, 127-142, 146-158, 162-199, 203-218, 222-239, 243-258, 262-269, 307-339, 344-358, 415-427, 446-451, 456-463 |
| packages/canvod-store-metadata/src/canvod/store\_metadata/validate.py           |       72 |       15 |     79% |12, 31, 55, 66, 76, 78, 80, 82, 84, 88, 103, 126, 137, 157, 171 |
| packages/canvod-store/src/canvod/store/\_\_init\_\_.py                          |        6 |        0 |    100% |           |
| packages/canvod-store/src/canvod/store/manager.py                               |      295 |      251 |     15% |72-95, 104, 109, 116, 129-131, 136, 160-163, 189-199, 211, 223-231, 249-285, 296, 313-327, 349-376, 401-426, 477-499, 530-558, 588-606, 634-658, 691-752, 774-810, 821-899, 925-982, 992, 1002-1004, 1023-1031 |
| packages/canvod-store/src/canvod/store/reader.py                                |      311 |      278 |     11% |45-67, 90-114, 161-205, 211-214, 218-221, 237, 245-248, 252-255, 269-458, 482-660, 664-667, 672-684, 693-718, 729-736, 746-747 |
| packages/canvod-store/src/canvod/store/store.py                                 |     1158 |      313 |     73% |41, 44-62, 65, 68, 82, 242, 248-253, 257-264, 409, 426, 448, 450, 456-481, 490-491, 497, 504-506, 525, 644, 649, 672, 685-687, 714, 820-823, 838-839, 879-942, 961, 990-1017, 1028, 1036, 1084-1118, 1143-1192, 1208-1264, 1288, 1323-1324, 1393-1394, 1481-1500, 1505, 1511, 1517, 1523, 1575-1576, 1593, 1601, 1627-1628, 1659, 1712-1729, 1739, 1750, 1906-1907, 1996-1998, 2153-2162, 2204, 2256-2344, 2391-2392, 2438-2445, 2649, 2651, 2852-2853, 2870-2871, 2901-2902, 2991, 3114, 3210-3212, 3218-3220, 3253-3261, 3446-3448, 3460-3473, 3603-3604, 3696-3717, 3732-3737, 3745-3746, 3844-3850, 3856-3860, 3876-3896, 3914-3920 |
| packages/canvod-store/src/canvod/store/viewer.py                                |      291 |      257 |     12% |40-47, 68, 76, 384-404, 408-422, 427-456, 477-522, 539-575, 599-621, 634-674, 678-699, 714-774, 782-847, 851-914, 925-1013, 1050-1051, 1060-1065, 1074, 1115-1126, 1143-1145 |
| packages/canvod-store/src/canvod/store/zarr\_concurrency.py                     |       16 |        0 |    100% |           |
| packages/canvod-utils/src/canvod/utils/\_\_init\_\_.py                          |        2 |        0 |    100% |           |
| packages/canvod-utils/src/canvod/utils/\_meta.py                                |        5 |        0 |    100% |           |
| packages/canvod-utils/src/canvod/utils/tools/\_\_init\_\_.py                    |        8 |        0 |    100% |           |
| packages/canvod-utils/src/canvod/utils/tools/date\_utils.py                     |      105 |       16 |     85% |37, 44, 125, 139, 155, 172, 174, 213, 229, 249, 331, 336, 348, 361, 392-393 |
| packages/canvod-utils/src/canvod/utils/tools/hashing.py                         |        9 |        6 |     33% |     32-37 |
| packages/canvod-utils/src/canvod/utils/tools/sanitize.py                        |       15 |        5 |     67% |     41-48 |
| packages/canvod-utils/src/canvod/utils/tools/validation.py                      |        7 |        5 |     29% |     29-33 |
| packages/canvod-utils/src/canvod/utils/tools/version.py                         |       22 |       14 |     36% |     42-61 |
| packages/canvod-utils/src/canvod/utils/tools/worker.py                          |       16 |       14 |     12% |     15-30 |
| packages/canvod-viz/src/canvod/viz/\_\_init\_\_.py                              |        6 |        0 |    100% |           |
| packages/canvod-viz/src/canvod/viz/hemisphere\_2d.py                            |      262 |      172 |     34% |37-39, 127-128, 136, 217, 228, 235-244, 271, 295-339, 349-386, 392-431, 437-475, 542, 588-589, 646-761 |
| packages/canvod-viz/src/canvod/viz/hemisphere\_3d.py                            |      360 |      272 |     24% |126-140, 202, 233-234, 260-295, 323-362, 390-439, 471-517, 541-563, 609, 621-691, 792-888, 919-962, 991-1056, 1114-1125 |
| packages/canvod-viz/src/canvod/viz/styles.py                                    |      123 |        1 |     99% |       506 |
| packages/canvod-viz/src/canvod/viz/visualizer.py                                |       52 |        3 |     94% |246, 351-352 |
| packages/canvod-vod/src/canvod/vod/\_\_init\_\_.py                              |        3 |        0 |    100% |           |
| packages/canvod-vod/src/canvod/vod/\_internal/\_\_init\_\_.py                   |        2 |        0 |    100% |           |
| packages/canvod-vod/src/canvod/vod/\_internal/logger.py                         |        5 |        1 |     80% |        26 |
| packages/canvod-vod/src/canvod/vod/calculator.py                                |       66 |        7 |     89% |51, 65, 106-112 |
| **TOTAL**                                                                       | **20285** | **10934** | **46%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/TUW-GEO/canvodpy/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/TUW-GEO/canvodpy/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/TUW-GEO/canvodpy/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/TUW-GEO/canvodpy/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2FTUW-GEO%2Fcanvodpy%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/TUW-GEO/canvodpy/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.