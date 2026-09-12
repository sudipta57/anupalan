/**
 * Hindi strings.
 *
 * Typed as a deep partial of English: any key missing here falls back to English at runtime
 * rather than rendering a raw key. That lets translation land incrementally without the app
 * ever showing `settings.appearance` to a user.
 *
 * What is filled in below is navigation, verdicts and the advisory disclaimer — the strings a
 * Hindi-speaking inspector reads on every single scan. The rest is stubbed for a translator.
 * Devanagari runs longer than English; check layouts at these strings, not at the English ones
 * (NFR-08).
 */

import type { Translations } from './en';

type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends string ? string : DeepPartial<T[K]>;
};

export const hi: DeepPartial<Translations> = {
  common: {
    appName: 'अनुपालन',
    cancel: 'रद्द करें',
    retry: 'फिर कोशिश करें',
    close: 'बंद करें',
    done: 'हो गया',
    next: 'आगे',
    back: 'पीछे',
    save: 'सहेजें',
    loading: 'लोड हो रहा है…',
    search: 'खोजें',
  },

  tabs: {
    scan: 'स्कैन',
    inspections: 'निरीक्षण',
    bulk: 'थोक जाँच',
    history: 'इतिहास',
    sahayak: 'सहायक',
    settings: 'सेटिंग्स',
  },

  verdict: {
    pass: 'उत्तीर्ण',
    fail: 'अनुत्तीर्ण',
    borderline: 'सीमावर्ती',
    notAssessable: 'आकलन योग्य नहीं',
    passDescription: 'आवश्यकता पूरी करता है।',
    failDescription: 'आवश्यकता पूरी नहीं करता।',
    borderlineDescription: 'माप अनिश्चितता की सीमा के भीतर है।',
    notAssessableDescription: 'इस छवि से मापा नहीं जा सका।',
  },

  disclaimer: {
    title: 'केवल परामर्शी — प्रमाणन नहीं',
    body: 'अनुपालन एक पूर्व-अंकेक्षण राय देता है। इसका कोई वैधानिक बल नहीं है और यह विधिक माप विज्ञान निरीक्षण या पेशेवर सलाह का विकल्प नहीं है।',
    rulepack: 'नियम पैक {version} के अनुसार जाँचा गया',
  },

  capture: {
    title: 'कैप्चर',
    permissionTitle: 'कैमरा अनुमति आवश्यक है',
    permissionGrant: 'कैमरा अनुमति दें',
    noDevice: 'कोई कैमरा नहीं मिला',
    gates: 'कैप्चर जाँच',
    gateMarker: 'मार्कर',
    gateBlur: 'स्पष्टता',
    gateGlare: 'चमक',
    gateTilt: 'कोण',
    gateMarkerFail: 'संदर्भ के चारों कोने फ़्रेम में लाएँ।',
    gateBlurFail: 'कैमरा स्थिर रखें या थोड़ा पीछे हटें।',
    gateGlareFail: 'चमक कम करें — प्रकाश हटाएँ या पैक को झुकाएँ।',
    gateTiltFail: 'कैमरा पैक के समकोण पर रखें।',
    gateTiltUnknown: 'जब तक संदर्भ फ़्रेम में नहीं है, कोण नहीं आँका जा सकता।',
    shutter: 'कैप्चर करें',
    shutterBlocked: 'हर जाँच पूरी होने तक कैप्चर बंद है',
    retake: 'अंतिम हटाएँ',
  },

  marker: {
    title: 'मापन संदर्भ',
    subtitle: 'मिलीमीटर तभी मापे जा सकते हैं जब उसी तस्वीर में ज्ञात आकार की कोई वस्तु हो।',
    why: 'यह क्यों आवश्यक है',
    choose: 'अपना संदर्भ चुनें',
    arucoName: 'मुद्रित मार्कर',
    id1Name: 'मानक कार्ड',
    userName: 'ज्ञात पैक माप',
    recommended: 'अनुशंसित',
    printTitle: '100% पर प्रिंट करें',
    printWarning:
      'यदि प्रिंटर पृष्ठ का आकार बदल देता है तो हर रिपोर्ट का हर मिलीमीटर उसी अनुपात में गलत हो जाएगा।',
    screenWarning:
      'स्क्रीन पर दिखाया गया मार्कर कभी मान्य नहीं है — उसका आकार अज्ञात है और वह प्रकाशित है। वह कागज़ पर होना चाहिए।',
    dimensionLabel: 'मापी गई दूरी',
    verifyTitle: 'उपयोग से पहले इसे मापें',
    save: 'संदर्भ सहेजें',
    change: 'संदर्भ बदलें',
    current: 'वर्तमान संदर्भ',
    notSet: 'कोई संदर्भ सेट नहीं',
    notSetBody: 'जब तक ऐप को यह पता न हो कि किसके सापेक्ष मापना है, स्कैन शुरू नहीं किया जा सकता।',
    setUp: 'संदर्भ सेट करें',
  },

  scan: {
    title: 'लेबल स्कैन करें',
    start: 'स्कैन शुरू करें',
    openTitle: 'एक स्कैन खुला है',
    openContinue: 'उत्पाद विवरण जोड़ें',
    openMore: 'और तस्वीरें लें',
    openDiscard: 'यह स्कैन हटाएँ',
  },

  processing: {
    title: 'स्कैन',
    waitingTitle: 'काम चल रहा है',
    stageUpload: 'छवि अपलोड हो रही है',
    stageRectify: 'ज्ञात पैमाने पर समतल किया जा रहा है',
    stageOcr: 'पाठ पढ़ा जा रहा है',
    stageMetrology: 'अक्षरों की ऊँचाई मापी जा रही है',
    stageExtraction: 'घोषणाएँ निकाली जा रही हैं',
    stageRules: 'नियम पैक के अनुसार मूल्यांकन',
    stageFindings: 'निष्कर्ष संकलित किए जा रहे हैं',
    stageReport: 'रिपोर्ट बनाई जा रही है',
    completeTitle: 'स्कैन पूर्ण',
    viewFindings: 'निष्कर्ष देखें',
    provisionalTitle: 'निर्णय अस्थायी हैं',
    noMarkerTitle: 'कोई मापन मार्कर नहीं मिला',
    noMarkerBody:
      'उपस्थिति और शब्दावली के नियम चले। आकार के सभी नियम “आकलन योग्य नहीं” हैं — ज्ञात आकार के संदर्भ के बिना कोई मिलीमीटर नहीं मापा जा सकता, और अनुमान अंतराल से भी बुरा होगा।',
    reducedTitle: 'सीमित निष्कर्षण',
    summaryPass: 'उत्तीर्ण',
    summaryFail: 'अनुत्तीर्ण',
    summaryBorderline: 'सीमावर्ती',
    summaryNotAssessable: 'आकलन योग्य नहीं',
    notFound: 'स्कैन नहीं मिला',
  },

  confirm: {
    title: 'पढ़े गए मान की पुष्टि करें',
    subtitle:
      'मशीन इन मानों के बारे में अनिश्चित थी। प्रत्येक को चित्र से मिलाएँ और गलत हो तो सुधारें — अनुमान पर कोई निर्णय नहीं दिया जाता।',
    readAs: 'पढ़ा गया',
    confidence: '{percent}% निश्चित',
    valueLabel: 'सही मान',
    accept: 'यह सही है',
    accepted: 'पुष्टि हो गई',
    saving: 'पुनर्गणना हो रही है…',
    recomputed: 'आपके सुधार के अनुसार निर्णय पुनः गणना किए गए।',
    allDone: 'सब पुष्ट हो गया',
    done: 'स्कैन पर वापस',
  },

  fields: {
    manufacturerName: 'निर्माता',
    manufacturerAddress: 'निर्माता का पता',
    packerName: 'पैकर',
    importerName: 'आयातक',
    importerAddress: 'आयातक का पता',
    countryOfOrigin: 'मूल देश',
    commonName: 'सामान्य नाम',
    netQuantity: 'शुद्ध मात्रा',
    mrp: 'अधिकतम खुदरा मूल्य',
    mfgMonthYear: 'निर्माण माह और वर्ष',
    consumerCareName: 'उपभोक्ता सेवा संपर्क',
    consumerCarePhone: 'उपभोक्ता सेवा फ़ोन',
    consumerCareEmail: 'उपभोक्ता सेवा ईमेल',
    unitSalePrice: 'इकाई विक्रय मूल्य',
    bestBefore: 'सर्वोत्तम उपयोग तिथि',
  },

  // An inspector working a market with no signal reads these strings more than any other screen.
  findings: {
    title: 'निष्कर्ष',
    selectHint: 'लेबल पर किसी रूपरेखा, या नीचे किसी निष्कर्ष को टैप करें।',
    fit: 'पूरा दिखाएँ',
    scaleBar: '{mm} मिमी',
    groupFail: 'विफल',
    groupBorderline: 'सीमावर्ती',
    groupNotAssessable: 'आकलन योग्य नहीं',
    groupPass: 'उत्तीर्ण',
    groupEmpty: 'इस पैक पर कोई नहीं।',
    required: 'अपेक्षित',
    observed: 'पाया गया',
    band: 'अनिश्चितता परिसर',
    citation: 'विधिक स्रोत',
    remediation: 'क्या बदलें',
    severityCritical: 'गंभीर',
    severityMajor: 'प्रमुख',
    severityMinor: 'छोटा',
    noImage: 'कोई समतल किया गया चित्र नहीं',
    notComplete: 'इस स्कैन के निष्कर्ष अभी तैयार नहीं हैं',
    openScan: 'स्कैन खोलें',
    lockedTitle: 'यह अभिलेख बंद है',
  },

  evidence: {
    title: 'साक्ष्य अभिलेख',
    imageHash: 'मूल चित्र SHA-256',
    findingsHash: 'निष्कर्ष SHA-256',
    capturedAt: 'कैप्चर समय (UTC)',
    location: 'स्थान',
    locationNone: 'दर्ज नहीं।',
    district: 'ज़िला',
    issuedAt: 'रिपोर्ट जारी',
    notIssued: 'अभी जारी नहीं।',
  },

  queue: {
    title: 'अपलोड कतार',
    subtitle: 'नेटवर्क मिलने तक स्कैन यहाँ रुकते हैं। ऑफ़लाइन होने पर कुछ भी नहीं खोता।',
    empty: 'कुछ प्रतीक्षा में नहीं',
    open: 'कतार खोलें',
    pending: '{count} स्कैन प्रतीक्षा में',
    pendingPlural: '{count} स्कैन प्रतीक्षा में',
    statusCaptured: 'उत्पाद विवरण चाहिए',
    statusQueued: 'नेटवर्क की प्रतीक्षा',
    statusUploading: 'अपलोड हो रहा है',
    statusProcessing: 'सर्वर पर प्रक्रियाधीन',
    statusComplete: 'पूर्ण',
    statusFailed: 'अपलोड नहीं हो सका',
    attempt: 'प्रयास {count} / {max}',
    retryNow: 'अब फिर कोशिश करें',
    photos: '{count} तस्वीर',
    photosPlural: '{count} तस्वीरें',
    discard: 'हटाएँ',
    finish: 'विवरण जोड़ें',
    openScan: 'यह स्कैन खोलें',
  },

  // The context form is filled in on every single scan, so it is translated ahead of the screens
  // an inspector sees once a week. Devanagari runs longer than English — check the field labels
  // and the segmented controls at these strings, not at the English ones (NFR-08).
  context: {
    title: 'उत्पाद का विवरण',
    subtitle: 'इनमें से तीन तय करते हैं कि कौन-से नियम लागू होंगे, इसलिए वे तीनों अनिवार्य हैं।',
    whyTitle: 'ये तीन क्यों अनिवार्य हैं',
    photos: '{count} तस्वीर जोड़ी गई',
    photosPlural: '{count} तस्वीरें जोड़ी गईं',
    reference: 'संदर्भ: {name} · {mm} मिमी',

    nameLabel: 'उत्पाद का नाम',
    nameHint: 'जैसा पैक पर छपा है',

    categoryLabel: 'श्रेणी',
    categorySearch: 'उत्पाद खोजें',
    categoryRequired: 'एक श्रेणी चुनें।',
    categoryChange: 'श्रेणी बदलें',

    packLabel: 'पैक का प्रकार',
    packFlexible: 'लचीला',
    packRigid: 'कठोर',
    packGlass: 'काँच',
    packCan: 'डिब्बा',
    packOther: 'अन्य',

    surfaceLabel: 'घोषणा किस तरह अंकित है?',
    surfaceHint: 'उभरे, ढाले या छिद्रित अक्षरों के लिए ऊँचाई की सीमा अधिक होती है।',
    surfacePrinted: 'मुद्रित',
    surfaceEmbossed: 'उभरा या ढाला हुआ',

    importedLabel: 'यह कहाँ बना है?',
    importedHint: 'आयातित पैक पर आयातक और मूल देश की घोषणा अनिवार्य है।',
    importedNo: 'भारत में निर्मित',
    importedYes: 'आयातित',

    quantityLabel: 'घोषित शुद्ध मात्रा',
    quantityHint: 'पैक पर छपा आंकड़ा और उसकी इकाई।',
    quantityValueLabel: 'मात्रा',
    quantityUnitLabel: 'इकाई',
    quantityValueInvalid: 'शून्य से बड़ी संख्या दर्ज करें।',
    quantityReading: '{value} {unit} दर्ज किया जा रहा है।',

    pdpLabel: 'मुख्य प्रदर्शन पट्ट का क्षेत्रफल',
    pdpHint: 'वर्ग सेंटीमीटर में, उस सतह का जिस पर घोषणाएँ अंकित हैं।',

    channelLabel: 'यह कहाँ बिक रहा है?',
    channelRetail: 'दुकान',
    channelEcommerce: 'ऑनलाइन सूची',

    locationTitle: 'समय और स्थान',
    locationAttach: 'वर्तमान स्थान जोड़ें',
    locationWorking: 'स्थान लिया जा रहा है…',
    locationAttached: 'स्थान जोड़ा गया',
    locationRemove: 'स्थान हटाएँ',
    locationOptional: 'वैकल्पिक। इसके बिना भी स्कैन बनाया जा सकता है।',
    districtLabel: 'जिला',

    submit: 'स्कैन बनाएँ',
    incomplete: 'स्कैन बनाने से पहले लाल रंग में चिह्नित फ़ील्ड पूरे करें।',

    createdTitle: 'स्कैन बन गया',
    createdRecorded: 'नियम इंजन क्या पढ़ेगा',
    createdQuantity: 'शुद्ध मात्रा',
    createdImported: 'मूल',
    createdSurface: 'सतह',
    createdDone: 'स्कैन पर वापस',
  },

  categories: {
    foodFlour: 'आटा और मैदा',
    foodRice: 'चावल और अनाज',
    foodPulses: 'दाल',
    foodOil: 'खाद्य तेल और घी',
    foodSpices: 'मसाले',
    foodDairy: 'दूध और डेयरी',
    foodBakery: 'बिस्कुट और बेकरी',
    foodSnacks: 'नमकीन और स्नैक्स',
    foodConfectionery: 'चॉकलेट और मिठाई',
    foodTeaCoffee: 'चाय और कॉफ़ी',
    foodBaby: 'शिशु आहार',
    foodWater: 'पैक्ड पेयजल',
    beverageSoftDrink: 'शीतल पेय',
    beverageJuice: 'जूस और फल पेय',
    personalSoap: 'साबुन और शैम्पू',
    personalCosmetics: 'सौंदर्य प्रसाधन',
    personalOral: 'दंत देखभाल',
    householdDetergent: 'डिटर्जेंट',
    householdCleaning: 'क्लीनर और कीटाणुनाशक',
    stationeryPaper: 'स्टेशनरी और कागज़',
    electronicsAccessory: 'इलेक्ट्रॉनिक सहायक उपकरण',
    electronicsAppliance: 'घरेलू उपकरण',
    textileGarment: 'वस्त्र',
    hardwareCement: 'सीमेंट और निर्माण सामग्री',
    hardwareFastener: 'हार्डवेयर',
    otherGeneral: 'अन्य',
  },

  auth: {
    phoneTitle: 'साइन इन करें',
    phoneSubtitle: 'हम आपके फ़ोन पर छह अंकों का कोड भेजेंगे।',
    phoneLabel: 'मोबाइल नंबर',
    phoneHint: '10 अंकों का भारतीय मोबाइल नंबर',
    phoneInvalid: '6, 7, 8 या 9 से शुरू होने वाला 10 अंकों का नंबर दर्ज करें।',
    sendCode: 'कोड भेजें',
    otpTitle: 'कोड दर्ज करें',
    otpSubtitle: '{phone} पर भेजा गया। यह {seconds} सेकंड में समाप्त होगा।',
    otpLabel: 'छह अंकों का कोड',
    otpInvalid: 'छह अंकों का कोड दर्ज करें।',
    verify: 'सत्यापित करें और साइन इन करें',
    changeNumber: 'दूसरा नंबर उपयोग करें',
    resend: 'नया कोड भेजें',
    signedOut: 'आपका सत्र समाप्त हो गया। जारी रखने के लिए फिर से साइन इन करें।',
  },

  account: {
    title: 'खाता',
    signedInAs: 'साइन इन किया हुआ',
    role: 'भूमिका',
    organisation: 'संगठन',
    mode: 'मोड',
    modeEnforcement: 'प्रवर्तन',
    modeIndustry: 'उद्योग',
    signOut: 'साइन आउट',
  },

  roles: {
    admin: 'प्रशासक',
    inspector: 'निरीक्षक',
    analyst: 'विश्लेषक',
    viewer: 'दर्शक',
  },

  inspections: {
    title: 'निरीक्षण',
    subtitle: 'आपके दर्ज किए गए स्कैन, उनके साक्ष्य विवरण के साथ।',
    empty: 'अभी कोई निरीक्षण नहीं',
  },

  bulk: {
    title: 'थोक जाँच',
    subtitle: 'एक साथ कई मार्केटप्लेस लिस्टिंग जाँचें।',
    empty: 'अभी कुछ जाँचा नहीं गया',
  },

  settings: {
    title: 'सेटिंग्स',
    language: 'भाषा',
    appearance: 'रूप',
    appearanceSystem: 'डिवाइस के अनुसार',
    appearanceLight: 'हल्का',
    appearanceDark: 'गहरा',
    about: 'परिचय',
  },

  errors: {
    title: 'कुछ गलत हो गया',
    notFound: 'नहीं मिला',
    goSignIn: 'साइन इन पर जाएँ',
    offline: 'कोई कनेक्शन नहीं। आपका काम सहेजा गया है और ऑनलाइन होने पर सिंक हो जाएगा।',
  },
};
