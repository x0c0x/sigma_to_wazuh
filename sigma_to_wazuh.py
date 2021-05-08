#!//usr/bin/python3
"""
    Author: Brian Kellogg

    Purpose: Sigma to Wazuh log parser.

    References:
        Sigma: https://github.com/SigmaHQ/sigma
        Wazuh: https://wazuh.com

    Complete parsing of Sigma logic is not implemented. Just simpler rules are converted presently.
    Rules skipped:
        - Any containing parentheses
        - Any using Sigma near logic
        - Any using a timeframe condition
    Stats on all the above will be reported by this script.
"""
import sys, os
import configparser
import bs4, re
from itertools import tee
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, Comment, tostring, ElementTree, parse, dump
from ruamel.yaml import YAML


class BuildRules(object):
    def __init__(self):
        self.config = configparser.ConfigParser()   
        configFilePath = r'./config.ini'
        self.config.read(configFilePath)
        self.rules_link = self.config.get('sigma', 'rules_link')
        self.low = self.config.get('levels', 'low')
        self.medium = self.config.get('levels', 'medium')
        self.high = self.config.get('levels', 'high')
        self.critical = self.config.get('levels', 'critical')
        self.no_full_log = self.config.get('options', 'no_full_log')
        self.alert_by_email = self.config.get('options', 'alert_by_email')
        self.email_levels = self.config.get('options', 'email_levels')
        self.rule_id_start = int(self.config.get('options', 'rule_id_start'))
        self.rule_id = int(self.config.get('options', 'rule_id_start'))
        self.out_file = self.config.get('sigma', 'out_file')
        self.root = self.create_root()
        # monkey patching prettify
        # reference: https://stackoverflow.com/questions/15509397/custom-indent-width-for-beautifulsoup-prettify
        orig_prettify = bs4.BeautifulSoup.prettify
        r = re.compile(r'^(\s*)', re.MULTILINE)
        def prettify(self, encoding=None, formatter="minimal", indent_width=4):
            return r.sub(r'\1' * indent_width, orig_prettify(self, encoding, formatter))
        bs4.BeautifulSoup.prettify = prettify

    def create_root(self):
        root = Element('group')
        root.set('name', 'sigma,')
        self.add_header_comment(root)
        return root

    def add_header_comment(self, root):
        comment = Comment("""
Author: Brian Kellogg
Sigma: https://github.com/SigmaHQ/sigma
Wazuh: https://wazuh.com
All Sigma rules licensed under DRL: https://github.com/SigmaHQ/sigma/blob/master/LICENSE.Detection.Rules.md
""")
        root.append(comment)

    def init_rule(self, level):
        rule = SubElement(self.root, 'rule')
        rule.set('id', str(self.rule_id))
        rule.set('level', self.get_level(level))
        return rule

    def convert_field_name(self, product, field):
        if product in self.config.sections():
            if field in self.config[product]:
                return self.config[product][field]
        return "full_log" # target full log if we cannot find the field

    def if_ends_in_space(self, value):
        """
            spaces at end of logic are being chopped, therefore hacking this fix
        """
        if value.endswith(' '):
            return '(?i)(?:' + value + ')'
        return '(?i)' + value

    def add_logic(self, rule, product, field, negate, value):
        logic = SubElement(rule, 'field')
        logic.set('name', self.convert_field_name(product, field))
        logic.set('negate', negate)
        logic.set('type', 'pcre2')
        logic.text = self.if_ends_in_space(value).replace(r'\*', r'.+') # assumption is all '*' are wildcards

    def get_level(self, level):
        if level == "critical":
            return self.critical
        if level == "high":
            return self.high
        if level == "medium":
            return self.medium
        
        return self.low

    def add_options(self, rule, level):
        options = SubElement(rule, 'options')
        ops = ""
        if self.no_full_log == 'yes':
            ops = "no_full_log"
        if self.alert_by_email == 'yes' and (level in self.email_levels):
            ops = ops + ",alert_by_email"
        options.text = ops

    def add_mitre(self, rule, tags):
        mitre = SubElement(rule, 'mitre')
        for t in tags:
            mitre_id = SubElement(mitre, 'id')
            mitre_id.text = t

    def add_sigma_author(self, rule, sigma_rule_auther):
        comment = Comment('Sigma Rule Author: ' + sigma_rule_auther)
        rule.append(comment)

    def add_sigma_link_comment(self, rule, sigma_rule_link):
        comment = Comment(self.rules_link + sigma_rule_link)
        rule.append(comment)

    def add_description(self, rule, title):
        description = SubElement(rule, 'description')
        description.text = title

    def add_sources(self, rule, sources):
        log_sources = ""
        for key, value in sources.items():
            if value and not key == 'definition':
                log_sources += value + ","
        groups = SubElement(rule, 'group')
        groups.text = log_sources

    def create_rule(self, sigma_rule, sigma_rule_link):
        level = sigma_rule['level']
        rule = self.init_rule(level)
        self.add_sigma_link_comment(rule, sigma_rule_link)
        # Add rule link and author
        if 'author' in sigma_rule:
            self.add_sigma_author(rule, sigma_rule['author'])
        if 'tags' in sigma_rule:
            self.add_mitre(rule, sigma_rule['tags'])
        self.add_description(rule, sigma_rule['title'])
        self.add_options(rule, level)
        self.add_sources(rule, sigma_rule['logsource'])
        self.rule_id += 1 
        return rule

    def write_rules_file(self):
        xml = bs4.BeautifulSoup(tostring(self.root), 'xml').prettify()

        # collapse some tags to single lines
        xml = re.sub(r'<id>\n\s+', r'<id>', xml)
        xml = re.sub(r'\s+</id>', r'</id>', xml)

        xml = re.sub(r'<description>\n\s+', r'<description>', xml)
        xml = re.sub(r'\s+</description>', r'</description>', xml)

        xml = re.sub(r'<options>\n\s+', r'<options>', xml)
        xml = re.sub(r'\s+</options>', r'</options>', xml)

        xml = re.sub(r'<group>\n\s+', r'<group>', xml)
        xml = re.sub(r'\s+</group>', r'</group>', xml)

        xml = re.sub(r'<field(.+)>\n\s+', r'<field\1>', xml)
        xml = re.sub(r'\s+</field>', r'</field>', xml)

        # fixup some output messed up by the above
        xml = re.sub(r'</rule></group>', r'</rule>\n</group>', xml)
        xml = xml.replace('<?xml version="1.0" encoding="utf-8"?>\n', '')

        with open(self.out_file, "w") as file:
            file.write(xml)


class ParseSigmaRules(object):
    def __init__(self):
        configParser = configparser.RawConfigParser()   
        configFilePath = r'./config.ini'
        configParser.read(configFilePath)
        self.process_experimental_rules = configParser.get('sigma', 'process_experimental')
        self.sigma_rules_dir = configParser.get('sigma', 'directory')
        self.sigma_rules = self.get_sigma_rules()
        self.error_count = 0
        self.converted_total = 0

    def get_sigma_rules(self):
        fname = []
        exclude = set(['deprecated'])
        for root, dirs, f_names in os.walk(self.sigma_rules_dir):
            dirs[:] = [d for d in dirs if d not in exclude]
            for f in f_names:
                fname.append(os.path.join(root, f))
        return fname

    def load_sigma_rule(self, rule_file):
        try:
            yaml = YAML(typ='safe')
            with open(rule_file) as file:
                sigma_raw_rule = file.read()
            sigma_rule = yaml.load(sigma_raw_rule)
            return sigma_rule
        except:
            self.error_count += 1
            return ""

    def fixup_condition(self, condition):
        """
            Replace spaces with _ when the words constitute a logic operation.
            Allows for easier tokenization.
        """
        if isinstance(condition, list):
            return [tok.replace('1 of them', '1_of_them')
                            .replace('all of them', 'all_of_them')
                            .replace('1 of', '1_of')
                            .replace('all of', 'all_of') 
                            for tok in condition]
        return condition.replace('1 of them', '1_of_them')\
                        .replace('all of them', 'all_of_them')\
                        .replace('1 of', '1_of')\
                        .replace('all of', 'all_of')

    def pairwise(self, iterable):
        "s -> (s0,s1), (s1,s2), (s2, s3), ..."
        a, b = tee(iterable)
        next(b, None)
        return zip(a, b)

    def remove_wazuh_rule(self, rules, rule):
        rules.root.remove(rule) # destroy the extra rule that is created
        rules.rule_id -= 1      # decrement the current rule id as last rule was removed

    def fixup_logic(self, logic):
        logic = str(logic)
        if len(logic) > 2:  # when converting to Wazuh pcre2 expressions, we don't need start and end wildcards
            if logic[0] == '*': logic = logic[1:]
            if logic[-1] == '*': logic = logic[:-1]
        return re.escape(logic)

    def handle_list(self, value):
        if isinstance(value, list):
            return ('|'.join([self.fixup_logic(i) for i in value]))
        return self.fixup_logic(value)

    def convert_transforms(self, key, value):
        if '|' in key:
            field, transform = key.split('|', 1)
            if transform == 'contains':
                return field, self.handle_list(value)
            if transform == 'contains|all':
                return field, value
            if transform == 'startswith':
                return field, '^(?:' + self.handle_list(value) + ')'
            if transform == 'endswith':
                return field, '(?:' + self.handle_list(value) + ')$'
        return key, self.handle_list(value)

    def handle_one_of_them(self, rules, rule, detection, sigma_rule, 
                            sigma_rule_link, product):
        self.remove_wazuh_rule(rules, rule)
        if isinstance(detection, dict):
            for k, v in detection.items():
                if k == "condition": continue
                if isinstance(v, dict):
                    for x, y in v.items():
                        rule = rules.create_rule(sigma_rule, sigma_rule_link)
                        field, logic = self.convert_transforms(x, y)
                        self.is_dict_list_or_not(logic, rules, rule, product, field, "no")

    def handle_keywords(self, rules, rule, sigma_rule, sigma_rule_link, product, logic, negate):
        """
            A condition set as keywords will have a list of fields to look for those keywords in.
        """
        if 'fields' in sigma_rule:
            for f in sigma_rule['fields']:
                self.is_dict_list_or_not(logic, rules, rule, product, f, negate)
                rule = rules.create_rule(sigma_rule, sigma_rule_link)
            self.remove_wazuh_rule(rules, rule)
            return
        rules.add_logic(rule, product, "full_log", negate, logic)

    def is_dict_logic(self, values, rules, product, rule, negate):
        for k, v in values.items():
            if isinstance(v, dict):
                self.is_dict_logic(v, rules, product, rule, negate)
                continue
            rules.add_logic(rule, product, k, negate, v)

    def is_dict_list_or_not(self, logic, rules, rule, product, field, negate):
        if isinstance(logic, dict):
            self.is_dict_logic(logic, rules, product, rule, negate)
            return
        if isinstance(logic, list): # if logic is still a list then its contain|all logic
            for l in logic:
                rules.add_logic(rule, product, field, negate, self.fixup_logic(l))
            return
        rules.add_logic(rule, product, field, negate, logic)

    def get_detection(self, detection, token):
        values = {}
        if isinstance(detection, list):
            for d in detection:
                if isinstance(d, dict):
                    for k, v in d.items():
                        values[k] = v
                    continue
                values[token] = detection # handle one deep detections
            return values
        for k, v in detection.items():
            values[k] = v
        return values

    def handle_fields(self, rules, rule, token, negate, is_or, sigma_rule, 
                        sigma_rule_link, detection, all_logic, product):
        neg = "no"
        if negate:
            neg = negate.pop()
            if negate and negate[-1] == '(':
                negate.append(neg)

        detections = self.get_detection(detection, token)

        if is_or: # or logic requires another Wazuh rule
            rule = rules.create_rule(sigma_rule, sigma_rule_link)

        for k, v in detections.items():
            field, logic = self.convert_transforms(k, v)
            if logic not in all_logic: # do not add duplicate logic to a rule, even if its negated
                all_logic.append(logic)
                if k == 'keywords':
                    self.handle_keywords(rules, rule, sigma_rule, sigma_rule_link, product, logic, neg)
                    continue
                self.is_dict_list_or_not(logic, rules, rule, product, field, neg)

        return False, negate, all_logic

    def get_product(self, sigma_rule):
        if 'logsource' in sigma_rule and 'product' in sigma_rule['logsource']:
            return sigma_rule['logsource']['product'].lower()
        return ""

    def handle_tokens(self, rules, tokens, sigma_rule, sigma_rule_link, rule_path):
        """
            Messy attempt at a Sigma logic condition lexer. I am not good at this yet.

            Need to be able to handle rules like below:
            https://github.com/SigmaHQ/sigma/tree/master/rules/network/zeek/zeek_smb_converted_win_susp_psexec.yml
            The above rule converted to one Wazuh rule would not produce expected detection. 
        """
        level = 0       # track logic paren nesting
        is_or = False   # or logic is not supported between logic statements in a Wazuh rule
        negate = []     # stack to track negation logic
        all_logic =[]   # track all logic used in a rule to ensure a rule does not contain duplicate logic
        product = self.get_product(sigma_rule)
        rule = rules.create_rule(sigma_rule, sigma_rule_link)
        for token in tokens:
            if token == '(':
                level += 1
                if negate:
                    last = negate.pop()
                    negate.append('(')
                    negate.append(last)
                continue
            if token == ')':
                if len(negate) > 1 and negate[-2] == '(':
                    negate.pop()
                    negate.pop()
                level -= 1
                continue
            if token.lower() == 'or':
                is_or = True
                all_logic =[] # clear logic list as we will be creating a new rule to handle OR logic
                continue
            if token.lower() == 'and': continue
            if token.lower() == 'not':
                if negate:
                    if negate[-1] != "yes":
                        negate.append('yes')
                    continue
                negate.append("yes")
                continue
            if token.lower() == '1_of_them':
                self.handle_one_of_them(rules, rule, sigma_rule['detection'], 
                                        sigma_rule, sigma_rule_link, product)
                continue
            #print(sigma_rule_link)
            is_or, negate, all_logic = self.handle_fields(rules, rule, token, negate, is_or, 
                                                        sigma_rule, sigma_rule_link, 
                                                        sigma_rule['detection'][token], 
                                                        all_logic, product)


class TrackStats(object):
    def __init__(self):
        self.near_skips = 0
        self.paren_skips = 0
        self.timeframe_skips = 0
        self.experimental_skips = 0
        self.rules_skipped = 0

    def check_for_logic_to_skip(self, detection, condition):
        """
            All logic conditions are not parsed yet.
            This procedure will skip Sigma rules we are not ready to parse.
        """
        skip = False
        if '|' in condition:
            skip = True
            self.near_skips += 1
        if '(' in condition:
            skip = True
            self.paren_skips += 1
        if 'timeframe' in detection:
            skip = True
            self.timeframe_skips += 1
        if '1_of ' in condition:
            skip = True
            self.rules_skipped += 1
        if 'all_of' in condition:
            skip = True
            self.rules_skipped += 1
            
        return skip

    def report_stats(self, error_count, sigma_rules_count, rule_id_start, rule_id_end):
        sigma_rules_converted = sigma_rules_count - self.rules_skipped
        sigma_rules_converted_percent = round((( sigma_rules_converted / sigma_rules_count) * 100), 2)
        print("\n\n" + "*" * 75)
        print(" Number of Sigma Experimental rules skipped: %s" % self.experimental_skips)
        print("    Number of Sigma TIMEFRAME rules skipped: %s" % self.timeframe_skips)
        print("        Number of Sigma PAREN rules skipped: %s" % self.paren_skips)
        print("         Number of Sigma NEAR rules skipped: %s" % self.near_skips)
        print("        Number of Sigma ERROR rules skipped: %s" % error_count)
        print("                  Total Sigma rules skipped: %s" % self.rules_skipped)
        print("                Total Sigma rules converted: %s" % sigma_rules_converted)
        print("-" * 55)
        print("                  Total Wazuh rules created: %s" % (rule_id_end - rule_id_start))
        print("-" * 55)
        print("                          Total Sigma rules: %s" % sigma_rules_count)
        print("                    Sigma rules converted %%: %s" % sigma_rules_converted_percent)
        print("*" * 75 + "\n\n")


def main():
    convert = ParseSigmaRules()
    wazuh_rules = BuildRules()
    stats = TrackStats()

    for rule in convert.sigma_rules:
        sigma_rule = convert.load_sigma_rule(rule)
        if not sigma_rule:
            stats.rules_skipped += 1
            print("ERROR loading Sigma rule: " + rule)
            continue

        if convert.process_experimental_rules == "no":
            if 'status' in sigma_rule:
                if sigma_rule['status'] == "experimental":
                    stats.rules_skipped += 1
                    stats.experimental_skips += 1
                    print("SKIPPED Sigma rule: " + rule)
                    continue

        conditions = convert.fixup_condition(sigma_rule['detection']['condition'])

        skip_rule = stats.check_for_logic_to_skip(sigma_rule['detection'], conditions)
        if skip_rule:
            stats.rules_skipped += 1
            print("SKIPPED Sigma rule: " + rule)
            continue
        #print(rule)

        # build the URL to the sigma rule, handle relative paths
        partial_url_path = rule.replace('/sigma/rules', '').replace('../', '/').replace('./', '/')

        if isinstance(conditions, list):
            for condition in conditions: # create new rule for each condition, needs work
                tokens = condition.strip().split(' ')
                convert.handle_tokens(wazuh_rules, tokens, sigma_rule, partial_url_path, rule)
            continue
        tokens = conditions.strip().split(' ')
        convert.handle_tokens(wazuh_rules, tokens, sigma_rule, partial_url_path, rule)

    # write out all Wazuh rules created
    wazuh_rules.write_rules_file()

    stats.report_stats(convert.error_count, len(convert.sigma_rules), 
                        wazuh_rules.rule_id_start, wazuh_rules.rule_id)


if __name__ == "__main__":
    main()