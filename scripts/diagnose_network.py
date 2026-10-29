import argparse
import json
from alphalab.network_diagnostics import GROUPS, group_report
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('group',choices=GROUPS)
    args=parser.parse_args()
    print(json.dumps(group_report(args.group),ensure_ascii=False))
