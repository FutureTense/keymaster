// https://gist.github.com/hagemann/382adfc57adbd5af078dc93feef01fe1
export function slugify(value: string, delimiter = '-'): string {
    const a = 'àáâäæãåāăąçćčđďèéêëēėęěğǵḧîïíīįìıİłḿñńǹňôöòóœøōõőṕŕřßśšşșťțûüùúūǘůűųẃẍÿýžźż·';
    const b = `aaaaaaaaaacccddeeeeeeeegghiiiiiiiilmnnnnoooooooooprrsssssttuuuuuuuuuwxyyzzz${delimiter}`;
    const p = new RegExp(a.split('').join('|'), 'g');

    let slugified;

    if (value === '') {
        slugified = '';
    } else {
        slugified = value
            .toString()
            .toLowerCase()
            // Replace special characters
            .replace(p, (c) => b.charAt(a.indexOf(c)))
            // Remove Commas between numbers
            .replace(/(\d),(?=\d)/g, '$1')
            // Replace all non-word characters
            .replace(/[^a-z0-9]+/g, delimiter)
            // Replace multiple delimiters with single delimiter
            .replace(new RegExp(`(${delimiter})\\1+`, 'g'), '$1')
            // Trim delimiter from start of text
            .replace(new RegExp(`^${delimiter}+`), '')
            // Trim delimiter from end of text
            .replace(new RegExp(`${delimiter}+$`), '');

        if (slugified === '') {
            slugified = 'unknown';
        }
    }

    return slugified;
}
