"""Conservative source-attribute boundary for non-content image pixels."""
VERSION = 'explicit-empty-alt-pixel-v1'


def noncontent_pixel(attributes):
    # Never infer tracking from URLs. Native image inputs are not images here.
    return (attributes.get('alt') == '' and
            str(attributes.get('width', '')).strip() == '1' and
            str(attributes.get('height', '')).strip() == '1' and
            not any(attributes.get(key) for key in ('title', 'aria-label', 'aria-labelledby')))
