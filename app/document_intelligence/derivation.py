import re
from .models import IntermediateDocument

SECTION_TYPES={"method":"MATERIALS_AND_METHODS","protocol":"PROTOCOL","result":"RESULTS","discussion":"DISCUSSION","taxonomic":"TAXONOMIC_TREATMENT","identification key":"IDENTIFICATION_KEY"}
def derive(document:IntermediateDocument):
    sections=[]; current=None
    for block in document.blocks:
        if block.kind=="heading":
            current={"heading":block.text,"type":next((v for k,v in SECTION_TYPES.items() if k in block.text.casefold()),"OTHER"),"blocks":[],"anchors":[]}; sections.append(current)
        if current is None: current={"heading":None,"type":"FRONT_MATTER","blocks":[],"anchors":[]}; sections.append(current)
        current["blocks"].append(block.text); current["anchors"].append(block.anchor.__dict__)
    for section in sections: section["complete_text"]="\n".join(section.pop("blocks"))
    protocols=[]; results=[]; treatments=[]; keys=[]
    method_sections=[s for s in sections if s["type"] in {"MATERIALS_AND_METHODS","PROTOCOL"}]
    if method_sections: protocols.append({"title":method_sections[0]["heading"] or "Canonical protocol","complete_text":"\n".join(s["complete_text"] for s in method_sections),"spans":sum((s["anchors"] for s in method_sections),[])})
    for s in sections:
        if s["type"]=="RESULTS": results.append({"title":s["heading"],"complete_text":s["complete_text"],"methods":protocols,"tables":document.tables,"media":document.media,"anchors":s["anchors"]})
        if s["type"]=="TAXONOMIC_TREATMENT": treatments.append({"accepted_name":s["heading"],"ordered_sections":[s],"anchors":s["anchors"]})
        if s["type"]=="IDENTIFICATION_KEY":
            nodes=[]
            for line in s["complete_text"].splitlines():
                m=re.match(r"^(\d+[a-z]?)\.?\s+(.+?)(?:\s+\.{2,}\s*(.+))?$",line)
                if m: nodes.append({"couplet":m.group(1),"lead":m.group(2),"target":m.group(3),"original":line})
            keys.append({"title":s["heading"],"nodes":nodes,"anchors":s["anchors"]})
    return {"sections":sections,"protocols":protocols,"results":results,"treatments":treatments,"keys":keys}
