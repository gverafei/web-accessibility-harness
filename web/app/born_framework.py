"""Historical callable compatibility without a design dependency or download."""
VERSION='no-prescribed-framework-v1'
def framework_assets(root):return {}
def embed_framework(document,assets):return document
def framework_evidence(assets):return {'name':'Source evidence','version':VERSION,'delivery':'No prescribed framework','sha256':{}}
