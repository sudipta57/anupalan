/**
 * English strings. This file is the source of truth for the key set — every other locale is
 * typed as a partial of it, so adding a key here is a compile-time prompt to translate it.
 *
 * Keep the shape shallow-ish and grouped by surface. Values may contain `{placeholders}`.
 */

export const en = {
  common: {
    appName: 'Anupalan',
    cancel: 'Cancel',
    retry: 'Try again',
    close: 'Close',
    done: 'Done',
    next: 'Next',
    back: 'Back',
    save: 'Save',
    loading: 'Loading…',
    search: 'Search',
  },

  tabs: {
    scan: 'Scan',
    inspections: 'Inspections',
    bulk: 'Bulk check',
    history: 'History',
    sahayak: 'Sahayak',
    settings: 'Settings',
  },

  verdict: {
    pass: 'Pass',
    fail: 'Fail',
    borderline: 'Borderline',
    notAssessable: 'Not assessable',
    passDescription: 'Meets the requirement.',
    failDescription: 'Does not meet the requirement.',
    borderlineDescription: 'Within the measurement uncertainty of the threshold.',
    notAssessableDescription: 'Could not be measured from this image.',
  },

  disclaimer: {
    title: 'Advisory only — not a certification',
    body: 'Anupalan gives a pre-audit opinion. It carries no legal force and does not replace a Legal Metrology inspection or professional advice.',
    rulepack: 'Checked against rule pack {version}',
    pending:
      'The rule pack is an engineering transcription of published rules, pending legal review.',
  },

  capture: {
    title: 'Capture',
    permissionTitle: 'Camera access is needed',
    permissionBody:
      'Anupalan measures the label from a photograph, so it needs the camera. Nothing is uploaded until you submit a scan.',
    permissionGrant: 'Allow camera access',
    permissionBlocked:
      'Camera access was declined. Turn it on for Anupalan in the system settings to continue.',
    noDevice: 'No camera found',
    noDeviceBody: 'This device reports no usable back camera, so a label cannot be photographed.',
    gates: 'Capture checks',
    gateBlur: 'Sharpness',
    gateGlare: 'Glare',
    gateTilt: 'Angle',
    gateBlurFail: 'Hold steadier or move slightly back — the edges are too soft to measure.',
    gateGlareFail: 'Reduce glare: move the light, or tilt the pack away from it.',
    gateTiltFail: 'Hold the camera square to the pack.',
    gateTiltUnknown:
      'No scale reference in frame, so the angle was not checked. Size rules will be Not assessable.',
    shutter: 'Capture',
    shutterBlocked: 'Capture is disabled until every check passes',
    capturedCount: '{count} photo captured',
    capturedCountPlural: '{count} photos captured',
    retake: 'Discard last',
    continueLabel: 'Add product details',
    continueHint: 'The photographs are kept on this device until you create the scan.',
    saveFailed: 'That photograph could not be saved. Try again.',
    usingReference: 'Measuring against: {name} · {mm} mm',
    simulated: 'Simulated frame checks',
    simulatedBody:
      'Dev only. The native marker detector is not wired up yet, so these gates are driven by a simulation.',
  },

  marker: {
    title: 'Scale reference',
    subtitle:
      'Millimetres can only be measured against something of a known size in the same photograph.',
    why: 'Why this is needed',
    whyBody:
      'Every size check in a report — numeral height, letter height — is a millimetre measurement. Without a reference of known size in frame, those rules return Not assessable rather than a guess.',
    choose: 'Choose your reference',
    arucoName: 'Printed marker',
    arucoDetail: 'A 40 mm tag printed from the sheet in this repo. Most reliable.',
    id1Name: 'Standard card',
    id1Detail: 'Any ID-1 card — debit, credit, Aadhaar, licence — 85.60 × 53.98 mm.',
    userName: 'Known pack dimension',
    userDetail: 'A dimension you have measured yourself. Last resort.',
    recommended: 'Recommended',
    printTitle: 'Print at 100%',
    printBody:
      'The sheet is at mobile/assets/marker/anupalan-marker-a4.pdf. Print it with scaling off — no “fit to page”, no “shrink to fit”.',
    printWarning:
      'A printer that scales the page makes every millimetre in every report wrong by the same factor, and nothing downstream can detect it.',
    screenWarning:
      'A marker shown on a screen is never valid: its size is unknown and it is backlit. It must be on paper.',
    dimensionLabel: 'Measured dimension',
    dimensionHint: 'In millimetres, between {min} and {max}',
    dimensionInvalid: 'Enter a dimension between {min} and {max} mm.',
    verifyTitle: 'Measure it before you use it',
    verifyAruco: 'I measured the printed tag with a ruler and each side is exactly 40 mm.',
    verifyId1: 'I checked my card against the outline and it matches exactly.',
    verifyUser: 'I measured this dimension with a ruler and it is exactly {mm} mm.',
    save: 'Save reference',
    change: 'Change reference',
    current: 'Current reference',
    verifiedOn: 'Verified {date}',
    notSet: 'No reference set up',
    notSetBody: 'A scan cannot be started until the app knows what to measure against.',
    setUp: 'Set up a reference',
  },

  scan: {
    title: 'Scan a label',
    subtitle: 'Photograph the package with the scale marker in frame.',
    start: 'Start a scan',
    openTitle: 'A scan is open',
    openBody: '{count} photograph taken, waiting for its product details.',
    openBodyPlural: '{count} photographs taken, waiting for their product details.',
    openContinue: 'Add product details',
    openMore: 'Take more photographs',
    openDiscard: 'Discard this scan',
    openDiscardConfirm: 'Discard it? The photographs stay on this device.',
  },

  processing: {
    title: 'Scan',
    waitingTitle: 'Working on it',
    awaitingTitle: 'Read, not yet judged',
    awaitingBody:
      '{count} field was read with low confidence. No verdict is issued until you check it — a rule asked about a value nobody has confirmed answers just as confidently as one that is right.',
    awaitingBodyPlural:
      '{count} fields were read with low confidence. No verdict is issued until you check them — a rule asked about a value nobody has confirmed answers just as confidently as one that is right.',
    awaitingAction: 'Check what was read',
    waitingBody: 'This usually takes under ten seconds on a good connection.',
    queuedTitle: 'Waiting to upload',
    queuedBody: 'It will go up as soon as there is a network. You can leave this screen.',
    stageUnknown: 'The server has not said which stage it is on.',
    stageUpload: 'Uploading the image',
    stageRectify: 'Flattening to a known scale',
    stageOcr: 'Reading the text',
    stageMetrology: 'Measuring glyph heights',
    stageExtraction: 'Picking out the declarations',
    stageRules: 'Evaluating the rule pack',
    stageFindings: 'Assembling the findings',
    stageReport: 'Building the report',

    completeTitle: 'Scan complete',
    completeBody: 'Checked against {count} rule.',
    completeBodyPlural: 'Checked against {count} rules.',
    viewFindings: 'View findings',

    failedTitle: 'This scan did not finish',
    failedBody: 'Nothing was lost. Retry it from the upload queue, or photograph the pack again.',

    provisionalTitle: 'Verdicts are provisional',
    provisionalBody:
      '{count} field was read with low confidence. A rule evaluated against a misread value can fail a pack that actually complies, so confirm it before reading the verdicts.',
    provisionalBodyPlural:
      '{count} fields were read with low confidence. A rule evaluated against a misread value can fail a pack that actually complies, so confirm them before reading the verdicts.',
    confirmCta: 'Confirm {count} field',
    confirmCtaPlural: 'Confirm {count} fields',

    noMarkerTitle: 'No scale marker was detected',
    noMarkerBody:
      'Presence and wording rules still ran. Every size rule is Not assessable — without a reference of known size there is no millimetre to measure, and a guess would be worse than a gap.',
    reducedTitle: 'Reduced extraction',
    reducedBody:
      'The language model was unavailable, so only the pattern-matched fields were read. The rules all ran; free-text declarations may be missing. The report carries this flag.',
    lowConfidenceTitle: 'A field needs confirming',
    lowConfidenceBody: 'One or more values were read with low confidence.',
    uploadFailedTitle: 'Upload failed',
    uploadFailedBody: 'The photographs are still on this device. Retry from the upload queue.',

    summaryPass: 'Pass',
    summaryFail: 'Fail',
    summaryBorderline: 'Borderline',
    summaryNotAssessable: 'Not assessable',
    notFound: 'Scan not found',
    notFoundBody: 'It may have been discarded, or it belongs to another organisation.',
  },

  confirm: {
    title: 'Confirm what was read',
    subtitle:
      'The machine was unsure of these. Check each against the crop and correct it if it is wrong — no verdict is issued on a guess.',
    readAs: 'Read as',
    confidence: '{percent}% confident',
    source: 'Read by {source}',
    sourceRegex: 'pattern matching',
    sourceLlm: 'the language model',
    sourceHuman: 'you',
    valueLabel: 'Correct value',
    valueEmpty: 'Enter the value as printed on the pack.',
    accept: 'This is correct',
    accepted: 'Confirmed',
    saving: 'Recomputing…',
    saveFailed: 'That correction could not be saved. Try again.',
    recomputing: 'Recomputing the verdicts…',
    recomputedSame:
      'Recomputed. No verdict changed — these rules ask whether a declaration is present, not what it says.',
    recomputedOne: 'Recomputed. 1 verdict changed.',
    recomputedMany: 'Recomputed. {count} verdicts changed.',
    allDone: 'Everything is confirmed',
    allDoneBody: 'No field on this scan is waiting on you.',
    done: 'Back to the scan',
    noCrop: 'No image region was recorded for this field.',
    unclearTitle: 'Also unclear ({count})',
    unclearBody:
      'Read below {percent}% confidence, so probably misread. They still need confirming before the verdicts are issued.',
    unclearShow: 'Show them',
    unclearHide: 'Hide them',
  },

  fields: {
    manufacturerName: 'Manufacturer',
    manufacturerAddress: 'Manufacturer address',
    packerName: 'Packer',
    importerName: 'Importer',
    importerAddress: 'Importer address',
    countryOfOrigin: 'Country of origin',
    commonName: 'Common or generic name',
    netQuantity: 'Net quantity',
    mrp: 'Retail sale price',
    mfgMonthYear: 'Month and year of manufacture',
    consumerCareName: 'Consumer care contact',
    consumerCarePhone: 'Consumer care phone',
    consumerCareEmail: 'Consumer care email',
    unitSalePrice: 'Unit sale price',
    bestBefore: 'Best before',
  },

  findings: {
    title: 'Findings',
    imageLabel: 'The rectified label, with each finding outlined',
    selectHint:
      'Tap an outline on the label, or a finding below, to see what the rule requires and read its source.',
    zoom: '{percent}%',
    fit: 'Fit',
    scaleBar: '{mm} mm',
    imageHint: 'Pinch to zoom. Drag to move.',

    groupFail: 'Failures',
    groupBorderline: 'Borderline',
    groupNotAssessable: 'Not assessable',
    groupPass: 'Passed',
    groupEmpty: 'None on this pack.',

    required: 'Required',
    observed: 'Observed',
    band: 'Uncertainty band',
    citation: 'Legal source',
    remediation: 'What to change',
    severityCritical: 'Critical',
    severityMajor: 'Major',
    severityMinor: 'Minor',

    noRegion: 'No region was recorded on the image for this rule.',
    noBoxTitle: '{count} finding has no region on the label',
    noBoxTitlePlural: '{count} findings have no region on the label',
    noBoxBody:
      'They are listed below but cannot be pointed at, so check them against the pack by hand. Every failure and borderline result is supposed to carry a region — report this if it persists.',

    noImage: 'No rectified image',
    noImageBody:
      'Findings are anchored to the rectified image and this scan has none, so there is nothing to draw the outlines on. The list below is complete.',

    awaitingTitle: 'No verdicts yet',

    awaitingBody:
      'This scan was read but not judged: a field came back with low confidence, and no rule is applied to a value nobody has checked. Confirm what was read and the verdicts follow.',

    notComplete: 'This scan has no findings yet',
    notCompleteBody: 'It is still on its way through the pipeline. The scan screen shows where.',
    openScan: 'Open the scan',

    lockedTitle: 'This record is closed',
    lockedBody:
      'A report has been issued over these findings and embeds their hash, so values can no longer be corrected here. Re-scan the pack to record a new reading.',
  },

  evidence: {
    title: 'Evidence record',
    body: 'What ties this result to one photograph, one moment and one place.',
    imageHash: 'Raw image SHA-256',
    imageHashMissing: 'Not recorded on this scan.',
    findingsHash: 'Findings SHA-256',
    capturedAt: 'Captured at (UTC)',
    location: 'Location',
    locationNone: 'Not recorded.',
    accuracy: '(±{metres} m)',
    district: 'District',
    districtNone: 'Not recorded.',
    issuedAt: 'Report issued',
    notIssued: 'Not issued yet.',
    pendingTitle: 'Hashes come from the server',
    pendingBody:
      'The audit chain is computed where the image is stored, not on this phone — a hash this app calculated would only cover what this app chose to send. Until the backend is connected these are fixture values.',
  },

  report: {
    title: 'Report',
    subtitle: 'Generate a PDF and a DOCX from this scan, then share them.',
    intro:
      'The report carries the findings table, the annotated label, both hashes and the rule pack version. It is the document someone else will read, so it is generated from the verdicts as they stand now.',

    formatPdf: 'PDF',
    formatPdfHint: 'For sending and printing. Annotated label and findings table.',
    formatDocx: 'Word (DOCX)',
    formatDocxHint: 'Same content, with the findings as a real editable table.',
    formatJson: 'JSON',
    formatJsonHint: 'Machine-readable. Fetched from the API, not shared from here.',
    chooseFormats: 'Formats',
    chooseFormatsBody: 'At least one. Both are generated together.',

    generate: 'Generate the report',
    generating: 'Generating…',
    generatingBody:
      'The annotated image and the findings table are rendered on the server. This usually takes a few seconds.',
    regenerate: 'Generate again',

    readyTitle: 'Report ready',
    readyBody: 'Generated {at}.',
    share: 'Share {format}',
    sharing: 'Opening the share sheet…',
    shareUnavailable: 'This device has nothing to share to.',
    shareFailed: 'That file could not be prepared for sharing. Try again.',
    downloadHint:
      'The file is copied to this device before sharing, so it works offline afterwards.',

    failedTitle: 'The report could not be generated',
    failedBody:
      'Nothing about the scan has changed. Its findings are still on the previous screen.',
    timedOutTitle: 'This is taking longer than it should',
    timedOutBody:
      'The report service has not answered in ninety seconds. Asking again renders it a second time, so give it a moment first.',
    emptyFile: 'This file came back empty and cannot be shared. Generate the report again.',
    missingFormats: 'The server did not produce: {formats}.',

    blockIncomplete: 'This scan has no findings yet',
    blockIncompleteBody:
      'A report can only be generated once the pipeline has finished. The scan screen shows where it is.',
    blockProvisional: 'Confirm the low-confidence fields first',
    blockProvisionalBody:
      'A rule evaluated against a misread value can fail a pack that actually complies. A screen can carry that caveat; a PDF in someone else\u2019s inbox cannot be taken back, so the report waits until the fields are confirmed.',
    blockNoFindings: 'There is nothing to report',
    blockNoFindingsBody:
      'This scan produced no findings at all, which is itself worth investigating before a report is issued.',
    openConfirm: 'Confirm the fields',

    integrity: 'What the report will carry',
    verdictCounts: 'Verdicts',
    issuedNotice: 'Issuing a report closes this record',
    issuedNoticeBody:
      'In enforcement mode, values can no longer be corrected once a report exists — the document embeds their hash.',
  },

  queue: {
    title: 'Upload queue',
    subtitle: 'Scans wait here until there is a network. Nothing is lost by going offline.',
    empty: 'Nothing waiting',
    emptyBody: 'Scans you complete appear here while they upload, and disappear once processed.',
    open: 'Open the queue',
    pending: '{count} scan waiting',
    pendingPlural: '{count} scans waiting',
    statusCaptured: 'Needs product details',
    statusQueued: 'Waiting for a network',
    statusUploading: 'Uploading',
    statusProcessing: 'Processing on the server',
    statusNeedsConfirmation: 'Waiting for you to confirm',
    statusComplete: 'Complete',
    statusFailed: 'Could not be uploaded',
    attempt: 'Attempt {count} of {max}',
    retryAt: 'Next attempt in {seconds} s',
    retryNow: 'Retry now',
    photos: '{count} photograph',
    photosPlural: '{count} photographs',
    uploaded: '{done} of {total} uploaded',
    reference: '{mm} mm reference',
    discard: 'Discard',
    discardBody: 'Removes it from the queue. The photographs stay on this device.',
    failedHint:
      'It stopped retrying after {max} attempts. Check the connection and retry, or discard it and photograph the pack again.',
    capturedHint: 'It has no product details yet, so there is nothing to upload.',
    finish: 'Add details',
    openScan: 'Open this scan',
  },

  context: {
    title: 'Product details',
    subtitle: 'Three of these decide which rules run, so none of the three is optional.',
    whyTitle: 'Why these three are mandatory',
    whyBody:
      'The net quantity picks the row that sets the minimum numeral height. The imported flag decides whether an importer and a country of origin are required at all. Embossed or moulded text must be larger than printed text to pass the same rule.',
    photos: '{count} photograph attached',
    photosPlural: '{count} photographs attached',
    reference: 'Shot against {name} · {mm} mm',

    nameLabel: 'Product name',
    nameHint: 'As printed on the pack',
    nameInvalid: 'Enter the name as printed, between 2 and {max} characters.',

    categoryLabel: 'Category',
    categoryHint:
      'Narrows which declarations apply, and which Indian Standard Sahayak checks later.',
    categorySearch: 'Search for the product',
    categoryNone: 'Nothing matches that. Try the common name — “atta”, “dal”, “charger”.',
    categoryRequired: 'Choose a category.',
    categoryChange: 'Change category',

    packLabel: 'Pack type',
    packFlexible: 'Flexible',
    packRigid: 'Rigid',
    packGlass: 'Glass',
    packCan: 'Can',
    packOther: 'Other',

    surfaceLabel: 'How is the declaration applied?',
    surfaceHint: 'Embossed, blown, moulded and perforated text carries a higher height threshold.',
    surfacePrinted: 'Printed',
    surfaceEmbossed: 'Embossed or moulded',

    importedLabel: 'Where was it made?',
    importedHint: 'An imported pack must declare the importer and the country of origin.',
    importedNo: 'Made in India',
    importedYes: 'Imported',

    quantityLabel: 'Declared net quantity',
    quantityHint: 'The figure printed on the pack, and its unit.',
    quantityValueLabel: 'Quantity',
    quantityUnitLabel: 'Unit',
    quantityValuePlaceholder: '500',
    quantityUnitPlaceholder: 'g',
    quantityValueInvalid: 'Enter a number greater than zero.',
    quantityUnitInvalid: 'Not a prescribed unit. Try one of {units}.',
    quantityRewritten: '“{typed}” is not a prescribed symbol. Recording {unit}.',
    quantityReading: 'Recording {value} {unit}.',
    basisWeight: 'Table I applies — the height threshold comes from the quantity itself.',
    basisCount: 'Table II applies — the height threshold comes from the display panel area.',

    pdpLabel: 'Principal display panel area',
    pdpHint: 'In square centimetres, measured on the face carrying the declarations.',
    pdpInvalid: 'Enter an area between 0 and {max} cm².',
    pdpWhy:
      'Sold by number or length, so the height rules read Table II — and Table II is keyed on this area. Without it those rules come back Not assessable.',

    channelLabel: 'Where is it being sold?',
    channelHint: 'Country of origin is required on an e-commerce listing under Rule 6(10A).',
    channelRetail: 'Retail shelf',
    channelEcommerce: 'Online listing',

    locationTitle: 'Time and place',
    locationBody:
      'This scan is stamped with the time it was taken. Attach the coordinates and they become part of the evidence trail on the record.',
    locationAttach: 'Attach current location',
    locationRetake: 'Take a new fix',
    locationWorking: 'Taking a fix…',
    locationAttached: 'Location attached',
    locationAccuracy: 'Accurate to about {metres} m',
    locationLoose: 'That fix is loose. Step into the open and take it again.',
    locationDenied:
      'Location access was declined. Turn it on for Anupalan in the system settings, or carry on without it.',
    locationUnavailable:
      'No fix available. Check that location is switched on, or carry on without it.',
    locationRemove: 'Remove location',
    locationOptional: 'Optional. A scan can be created without it.',
    districtLabel: 'District',
    districtHint: 'Used for district-level reporting.',

    noLocationTitle: 'No location collected',
    noLocationBody:
      'This is a pre-print artwork check rather than a field inspection, so no coordinates are recorded.',

    prefillGateTitle: 'Reading the label',
    prefillGateBody:
      'Checking every photograph for the declarations, so the details below arrive filled in rather than blank.',
    prefillGateNote: 'This needs a network. Without one, go straight to the form.',
    prefillGateSkip: 'Fill it in myself',
    prefillReading: 'Reading the label…',
    prefillReadingBody:
      'Fill anything in yourself if you would rather not wait — nothing here waits for the network.',
    prefillFilled: 'Filled {count} field from the label',
    prefillFilledPlural: 'Filled {count} fields from the label',
    prefillCheck: 'Check each one against the pack in your hand before creating the scan.',
    prefillNothing: 'Nothing readable on the label',
    prefillNothingBody:
      'The photograph was read but no declaration could be made out. Fill the details in below.',
    prefillFrom: 'Read from the label: “{text}”',
    prefillUnsure: 'Read from the label, but unclear: “{text}”. Check this one.',
    prefillConfirmTitle: 'Confirm what was read',
    prefillConfirmBody:
      'These decide which rules run, so they are yours to confirm rather than ours to assume.',
    prefillConfirmQuantity: 'Net quantity: {value}',
    prefillConfirmImported: 'Origin: imported',
    prefillConfirmAction: 'Matches the pack',
    prefillConfirmed: 'Confirmed',
    prefillUnconfirmed: 'Confirm the values read from the label before creating the scan.',

    submit: 'Create scan',
    submitFailed: 'The scan could not be created. Your photographs and details are still here.',
    incomplete: 'Finish the fields marked in red before creating the scan.',

    createdTitle: 'Scan created',
    createdBody: 'The product context is recorded against {count} photograph.',
    createdBodyPlural: 'The product context is recorded against {count} photographs.',
    createdPending:
      'It is in the upload queue now. It will go up as soon as there is a network, and nothing is lost if there is not.',
    createdRecorded: 'What the rules engine will read',
    createdQuantity: 'Net quantity',
    createdImported: 'Origin',
    createdSurface: 'Surface',
    createdBasis: 'Rule 9 table',
    createdDone: 'Back to Scan',

    noDraftTitle: 'Nothing to describe yet',
    noDraftBody: 'Product details belong to a capture. Photograph a pack first.',
    noDraftAction: 'Go to Scan',
  },

  categories: {
    foodFlour: 'Flour and atta',
    foodRice: 'Rice and grains',
    foodPulses: 'Pulses and dal',
    foodOil: 'Edible oil and ghee',
    foodSpices: 'Spices and masala',
    foodDairy: 'Milk and dairy',
    foodBakery: 'Biscuits and bakery',
    foodSnacks: 'Snacks and namkeen',
    foodConfectionery: 'Chocolate and confectionery',
    foodTeaCoffee: 'Tea and coffee',
    foodBaby: 'Baby and infant food',
    foodWater: 'Packaged drinking water',
    beverageSoftDrink: 'Soft and energy drinks',
    beverageJuice: 'Juices and fruit drinks',
    personalSoap: 'Soap and shampoo',
    personalCosmetics: 'Cosmetics and creams',
    personalOral: 'Oral care',
    householdDetergent: 'Detergents',
    householdCleaning: 'Cleaners and disinfectants',
    stationeryPaper: 'Stationery and paper',
    electronicsAccessory: 'Electronic accessories',
    electronicsAppliance: 'Home appliances',
    textileGarment: 'Garments and textiles',
    hardwareCement: 'Cement and construction',
    hardwareFastener: 'Hardware and fasteners',
    otherGeneral: 'Something else',
  },

  history: {
    title: 'History',
    subtitle: 'Every scan you have completed, newest first.',
    search: 'Search',
    searchPlaceholder: 'Product name',
    filters: 'Filters',
    filtersActive: 'Filters ({count})',
    clear: 'Clear filters',
    filterVerdict: 'Verdict',
    filterVerdictHint:
      'One at a time. Borderline is not a failure, so a failures filter never includes it.',
    filterRange: 'Date',
    rangeAny: 'Any date',
    rangeToday: 'Today',
    rangeWeek: 'Last 7 days',
    rangeMonth: 'Last 30 days',
    filterProduct: 'Product',
    filterDistrict: 'District',
    today: 'Today',
    yesterday: 'Yesterday',
    noMatches: 'Nothing matches those filters',
    noMatchesBody:
      'Every scan is still here. Widen the date range or clear the filters to see them.',
    empty: 'No scans yet',
    emptyBody: 'Scans you complete will be listed here, filterable by date, product and verdict.',
  },

  sahayak: {
    title: 'Sahayak',
    subtitle: 'Questions about Indian Standards and BIS certification.',
    empty: 'Ask about a Quality Control Order, a scheme, fees, or which lab to use.',
    emptyHint:
      'Answers come from public BIS material and are cited. Sahayak does not quote the text of a standard.',

    suggestion1: 'Does a phone charger need BIS registration?',
    suggestion2: 'Which purities can be hallmarked?',
    suggestion3: 'What is the difference between ISI and CRS?',

    inputLabel: 'Your question',
    inputPlaceholder: 'Ask about a QCO, a scheme, or a certification route',
    send: 'Ask',
    sending: 'Asking…',
    charactersLeft: '{count} characters left',
    tooLong:
      'Shorten the question to {max} characters. A truncated question gets answered accurately — but it is not the question you asked.',
    clear: 'Clear conversation',
    you: 'You',

    outcomeAnswered: 'From official sources',
    outcomeAnsweredBody: 'Cited below. Check the sources before relying on this.',
    outcomeNotFound: 'Not found in official sources',
    outcomeNotFoundBody:
      'The public Quality Control Orders and product lists available to Sahayak do not cover this, and it will not infer one that may not exist. Check the official page below — these orders are notified and amended frequently.',
    outcomeRefused: 'Cannot quote a standard',
    outcomeRefusedBody:
      'The full texts of Indian Standards are copyrighted and sold by BIS, so clause text, test limits and tolerance tables are outside what Sahayak will quote. It can tell you whether a Quality Control Order makes a standard mandatory, which route applies, and where to buy the standard.',

    downgradedTitle: 'Answer withheld — no official source',
    downgradedBody:
      'Sahayak produced an answer but cited nothing that could be traced to an official BIS or gazette page, so the answer is not shown. An uncited answer about certification is a guess, and this tool does not guess.',

    sourcesSupport: 'Sources',
    sourcesSignpost: 'Where to check',
    sourceQco: 'Quality Control Order',
    sourceIsiList: 'ISI mark product list',
    sourceCrsList: 'CRS product list',
    sourceSchemeGuide: 'Scheme guide',
    sourceFaq: 'BIS FAQ',
    sourceHallmarking: 'Hallmarking',
    sourceLabDirectory: 'Laboratory directory',
    sourceCatalogue: 'Standards catalogue',
    openHint: 'Opens the official page',
    openFailed: 'Could not open that page. No browser on this device would take the link.',
    withheld: '{count} source could not be traced to an official page and is not shown.',
    withheldPlural: '{count} sources could not be traced to official pages and are not shown.',

    asOf: 'Sources as of {date}',
    freshnessFresh: 'Current',
    freshnessAgeing: 'Sources over {days} days old',
    freshnessStale: 'Sources over a year old',
    freshnessUnknown: 'Source date unknown',
    recheck:
      'Quality Control Orders are amended constantly. Check the official page before acting on this.',
    confidence: 'Retrieval confidence {percent}%',

    askFailed: 'Could not reach Sahayak',
  },

  bis: {
    title: 'BIS requirement',
    subtitle: 'Whether this product needs BIS certification, and by which route.',
    cta: 'Check BIS requirement',
    ctaHint: 'Uses this scan\u2019s product details',
    product: 'Product',
    pending: 'Checking the public lists…',

    stanceRequired: 'BIS certification is required',
    stanceRequiredBody:
      'A Quality Control Order covers this product, so certification is mandatory before it is sold in India.',
    stanceNotRequired: 'BIS certification is not required',
    stanceNotRequiredBody:
      'No Quality Control Order in the public lists covers this product. Other regulators may still apply.',
    stanceUndetermined: 'Not established',
    stanceUndeterminedBody:
      'The public Quality Control Orders and product lists do not settle whether this product needs certification. This is not a finding that it is exempt — treat it as unanswered and confirm against the current list before relying on it.',

    schemeLabel: 'Certification route',
    schemeIsi: 'ISI mark',
    schemeIsiBody:
      'Certification against an Indian Standard, with a factory audit and ongoing surveillance.',
    schemeCrs: 'Compulsory Registration Scheme',
    schemeCrsBody:
      'Registration on a test report from a BIS-recognised laboratory. No factory audit, which is what separates CRS from the ISI mark scheme.',
    schemeFmcs: 'Foreign Manufacturers Certification Scheme',
    schemeFmcsBody: 'The ISI mark route for a manufacturer outside India.',
    schemeNone: 'No route applies',
    schemeNoneBody:
      'No certification route applies, because no Quality Control Order covers this product.',

    isNumbersRequired: 'Standards to certify against',
    isNumbersCandidate: 'Possibly relevant standards',
    isNumbersHint: 'Sahayak cannot quote the content of these standards. Buy them from BIS.',
    nextSteps: 'Next steps',
    sources: 'Sources',

    inconsistentTitle: 'Incomplete record',
    inconsistentBody:
      'This record says certification is mandatory but names no route to obtain it. That is a gap in the source data rather than an answer — confirm against the current list before acting.',

    notFoundTitle: 'No applicability record',
    notFoundBody:
      'Sahayak has no BIS applicability record for this product category. Ask about it in the chat, or check the official list of products under compulsory certification.',

    lookupFailed: 'The applicability lookup could not be completed',
    lookupFailedBody:
      'The public lists could not be checked just now. The chat below still works, but nothing in it is a determination — re-run the check before relying on an answer.',

    askTitle: 'Ask about this product',
    askBody:
      'Sahayak knows what you scanned. It answers from published BIS material and cites every source. It does not decide whether certification applies \u2014 the check above does that.',
    suggestion1: 'Does this product need BIS certification?',
    suggestion2: 'Which scheme would apply, ISI or CRS?',
    suggestion3: 'How do I apply for a licence for this product?',
  },

  auth: {
    phoneTitle: 'Sign in',
    phoneSubtitle: 'We will send a six-digit code to your phone.',
    phoneLabel: 'Mobile number',
    phoneHint: '10-digit Indian mobile number',
    phoneInvalid: 'Enter a 10-digit mobile number starting 6, 7, 8 or 9.',
    sendCode: 'Send code',
    otpTitle: 'Enter the code',
    otpSubtitle: 'Sent to {phone}. It expires in {seconds} seconds.',
    otpLabel: 'Six-digit code',
    otpInvalid: 'Enter the six-digit code.',
    verify: 'Verify and sign in',
    changeNumber: 'Use a different number',
    resend: 'Send a new code',
    signedOut: 'Your session ended. Sign in again to continue.',
    fixtureAccounts: 'Fixture accounts',
    fixtureHint: 'Dev only. Any code works except an obviously wrong one — try 000000.',
  },

  account: {
    title: 'Account',
    signedInAs: 'Signed in as',
    role: 'Role',
    organisation: 'Organisation',
    mode: 'Mode',
    modeEnforcement: 'Enforcement',
    modeIndustry: 'Industry',
    modeEnforcementBody:
      'Field inspection: geo-tagged evidence, an audit trail, and district reporting.',
    modeIndustryBody: 'Pre-print checks, bulk listing checks, and BIS applicability guidance.',
    signOut: 'Sign out',
  },

  roles: {
    admin: 'Administrator',
    inspector: 'Inspector',
    analyst: 'Analyst',
    viewer: 'Viewer',
  },

  inspections: {
    title: 'Inspections',
    subtitle: 'Scans you have recorded, with their evidence trail.',
    empty: 'No inspections yet',
    emptyBody:
      'Completed inspections are listed here with their district, timestamp and evidence hashes.',
  },

  bulk: {
    title: 'Bulk check',
    subtitle: 'Check many marketplace listings at once.',
    empty: 'Nothing checked yet',
    emptyBody:
      'Paste or upload a CSV of listing URLs or listing text. Metric rules stay Not assessable — a listing carries no physical scale.',

    inputLabel: 'Listings',
    inputPlaceholder:
      'One listing per line — a marketplace URL, or the listing text itself. CSV pasted from a spreadsheet works.',
    inputHint: 'Up to {max} listings. One per line.',
    check: 'Check {count} listing',
    checkPlural: 'Check {count} listings',
    checking: 'Checking…',
    clear: 'Clear',

    parsedRows: '{count} listing ready',
    parsedRowsPlural: '{count} listings ready',
    parsedBlank: '{count} blank line skipped',
    parsedBlankPlural: '{count} blank lines skipped',
    parsedDuplicates: '{count} duplicate collapsed',
    parsedDuplicatesPlural: '{count} duplicates collapsed',
    parsedTooLong: '{count} line was too long and was dropped',
    parsedTooLongPlural: '{count} lines were too long and were dropped',

    blockOverLimit: 'Too many listings',
    blockOverLimitBody:
      '{over} more than the limit of {max}. Nothing is checked until you trim the list — checking the first {max} and showing a table of {max} would read as a clean result for all {total}.',
    blockNothing: 'Nothing to check',
    blockNothingBody: 'Paste at least one marketplace URL or one line of listing text.',

    scaleTitle: 'Measurement rules cannot run on a listing',
    scaleBody:
      'A listing carries no physical scale, so every Rule 9 millimetre check comes back Not assessable. To check letter and numeral heights, photograph the pack with a printed marker.',

    resultsTitle: 'Results',
    resultsSummary: '{rows} listings · {findings} rule checks',
    listingsWithFail: '{count} with a failure',
    listingsWithBorderline: '{count} borderline',
    listingsClean: '{count} with nothing against them',
    listingsErrored: '{count} with no result',
    findingCounts: 'Rule checks across all listings',

    rowLabel: 'Line {line}',
    rowHint: 'Show the rule checks for this listing',
    rowErrorTitle: 'No result for this listing',
    kindUrl: 'URL',
    kindText: 'Listing text',
    observed: 'Listing says: {value}',

    reasonNoScale:
      'Not assessable — a listing carries no physical scale, so no millimetre can be measured.',
    reasonNotInListing:
      'Not assessable from listing text — this rule is about the marketplace page, not the listing copy. Submit the URL to check it.',
    reasonRowUnreadable: 'Not assessable — this listing could not be read.',

    guardTitle: 'Measurement verdicts were rejected',
    guardBody:
      '{count} rule check came back with a measured verdict on a listing, which is not possible — a listing has no physical scale. They have been forced to Not assessable and should be reported as a server fault.',
    guardBodyPlural:
      '{count} rule checks came back with measured verdicts on listings, which is not possible — a listing has no physical scale. They have been forced to Not assessable and should be reported as a server fault.',

    export: 'Export CSV',
    exporting: 'Preparing…',
    exportFailed: 'Could not export the results.',
    exportDialog: 'Share listing check results',

    checkFailed: 'The listing check could not be completed',
    pickFileUnavailable:
      'Picking a CSV file needs a capability this build does not have yet. Paste the file contents instead — a CSV copied from a spreadsheet works.',
  },

  settings: {
    title: 'Settings',
    language: 'Language',
    languageEnglish: 'English',
    languageHindi: 'हिन्दी',
    appearance: 'Appearance',
    appearanceSystem: 'Follow device',
    appearanceLight: 'Light',
    appearanceDark: 'Dark',
    about: 'About',
    version: 'Version {version}',
  },

  errors: {
    title: 'Something went wrong',
    generic:
      'The app hit an unexpected problem. Try again, and if it keeps happening, note what you were doing.',
    offline: 'No connection. Your work is saved and will sync when you are back online.',
    notFound: 'Not found',
    notFoundBody: 'That screen does not exist.',
    goHome: 'Go to Scan',
    goSignIn: 'Go to sign in',
  },
} as const;

export type Translations = typeof en;
