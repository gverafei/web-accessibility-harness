(() => {
    const formatter = new Intl.NumberFormat('en-US', { maximumFractionDigits: 20 });
    // Numeric query parameters in review URL fields must remain literal.
    const skipped = 'a,code,pre,script,style,time,input,textarea,select,option,[data-no-number-format],.review-url';
    const grouped = value => {
        if (/^0\d/.test(value)) return value;
        const [integer, decimal] = value.split('.');
        return `${formatter.format(Number(integer))}${decimal === undefined ? '' : `.${decimal}`}`;
    };
    const formatText = node => {
        const parent = node.parentElement;
        if (!parent || parent.closest(skipped)) return;
        let value = node.nodeValue;
        value = value.replace(/(?<![#\w./:-])(\d{4,}(?:\.\d+)?)(?=s\b)/g, match => grouped(match));
        value = value.replace(/(?<![#\w./:-])(\d{4,}(?:\.\d+)?)(?=\s+(?:tokens?|issues?|credits?|pages?|removed|calls?|URLs?)\b)/gi, match => grouped(match));
        value = value.replace(/(?<![#\w./:-])(\d{5,}(?:\.\d+)?)(?![\w./:-])/g, match => grouped(match));
        if (parent.tagName === 'STRONG') {
            value = value.replace(/^\s*(\d{4,}(?:\.\d+)?)\s*$/, match => grouped(match.trim()));
        }
        if (value !== node.nodeValue) node.nodeValue = value;
    };
    const formatTree = root => {
        if (root.nodeType === Node.TEXT_NODE) return formatText(root);
        if (!(root instanceof Element) || root.matches(skipped)) return;
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) formatText(node);
    };
    formatTree(document.body);
    new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(formatTree)))
        .observe(document.body, { childList: true, subtree: true });
})();
