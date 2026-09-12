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
