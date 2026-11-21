export const language = localStorage.getItem('language') === 'en' ? 'en' : 'vi';
export const tr = (vi: string, en: string) => language === 'en' ? en : vi;

document.documentElement.lang = language;
document.title = 'ConceptLens · ' + tr('Gia sư cá nhân', 'Personal tutor');
