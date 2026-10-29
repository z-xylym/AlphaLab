"""CLI alternative for a trusted platform terminal; never dumps HTTP data."""
import argparse
from alphalab.market_diagnostics import PROBES, probe

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('endpoint',choices=PROBES)
    args=parser.parse_args()
    category=probe(args.endpoint)
    print(args.endpoint+': '+category)
    return 0 if category=='CONNECTED' else 1
if __name__=='__main__':raise SystemExit(main())
