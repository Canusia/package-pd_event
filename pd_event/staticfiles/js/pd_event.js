
jQuery(document).ready(function($) {
    $('.datetime_picker').mask('00/00/0000 #0:00 ZM', {
        translation: {
            'Z': {
            pattern: /[AP]/, optional: true
            },
            'M': {
            pattern: /[M]/, optional: true
            }
        }
    });    
});
