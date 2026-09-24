package benchmark

// Symbol maps a bare index code to the eastmoney symbol format (market
// prefix): 399xxx are Shenzhen indices, everything else defaults to
// Shanghai; codes that already carry a prefix are passed through as-is.
// Which exchange an index belongs to is index domain knowledge, kept out
// of the transport adapters.
func Symbol(indexCode string) string {
	if len(indexCode) > 6 || (len(indexCode) > 0 && indexCode[0] != '0' && indexCode[0] != '3') {
		return indexCode
	}
	if len(indexCode) == 6 && indexCode[:3] == "399" {
		return "sz" + indexCode
	}
	return "sh" + indexCode
}
