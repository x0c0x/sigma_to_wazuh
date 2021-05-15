#!//usr/bin/python3
"""
    Author: Brian Kellogg

    Purpose: Get Wazuh rule information and report out in CSV.
"""


import os
import xml.etree.ElementTree as etree


class WazuhRules(object):
    def __init__(self):
        self.rule_dirs = ['/var/ossec/ruleset/rules', '/var/ossec/etc/rules']
        self.rule_files = self.get_wazuh_rule_files()
        self.rules = self.load_wazuh_rules()

    def get_wazuh_rule_files(self):
        fname = []
        for dir in self.rule_dirs:
            for root, dirs, f_names in os.walk(dir):
                for f in f_names:
                    fname.append(os.path.join(root, f))
        return fname

    def load_wazuh_rule(self, rule_file):
        try:
            with open(rule_file) as file:
                raw_xml = '<rules>' + file.read() + '</rules>'
            return etree.ElementTree(etree.fromstring(raw_xml))
        except Exception as e:
            print("ERROR: unable to load %si -> %s" % (rule_file, e))
            return None

    def load_wazuh_rules(self):
        rules = []
        for f in self.rule_files:
            temp = self.load_wazuh_rule(f)
            if temp:
                rules.append(self.load_wazuh_rule(f))
        return rules


class Report(object):
    def __init__(self, rules):
        self.csv = []
        self.final_csv = []
        self.rules = rules

    def init_print_vars(self):
        ifsid = None
        rid = None
        level = None
        description = None
        fields = []
        return rid, level, description, ifsid, fields

    def parse_rules(self):
        self.csv.append('"id"\t"level"\t"description"\t"fields"\t"parents"')
        for r in self.rules:
            rid, level, description, ifsid, fields = self.init_print_vars()
            new_rule = 0
            for e in r.iter():
                if e.tag == 'rule':
                    new_rule += 1
                    if new_rule == 2:
                        self.csv.append('"{}"\t"{}"\t"{}"\t"{}"\t"{}"'.format(rid, level, description, fields, ifsid))
                        rid, level, description, ifsid, fields = self.init_print_vars()
                        new_rule = 0
                    rid = e.attrib.get('id')
                    level = e.attrib.get('level')
                elif e.tag == 'description':
                    description = e.text
                elif e.tag == 'if_sid':
                    ifsid = e.text
                elif e.tag == 'field':
                    fields.append(e.attrib.get('name'))

    def find_children(self):
        self.final_csv.append('"id","level","description","fields","parents","children"')
        for outer in self.csv[1:]:
            children = []
            rule_id = outer.split("\t")[0]
            for inner in self.csv[1:]:
                fields = inner.split("\t")
                ifsids = [s.strip() for s in fields[4].split(',')]
                if rule_id in ifsids:
                    children.append(fields[0])
            if children:
                children = [int(i.strip('"')) for i in children]
            self.final_csv.append('{},"{}"'.format(outer.replace('\t',','), str(children).strip('[]')))

    def write_report(self):
        with open('wazuh_rule_report.csv', 'w') as file:
            for line in self.final_csv:
                file.write(line + "\n")


def main():
    wazuh_rules = WazuhRules()
    report = Report(wazuh_rules.rules)
    report.parse_rules()
    report.find_children()
    report.write_report()

if __name__ == "__main__":
    main()