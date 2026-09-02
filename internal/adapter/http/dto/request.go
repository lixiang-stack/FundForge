package dto

type SubscribeFundReq struct {
	FundCode string `json:"fund_code" binding:"required"`
}

type BindStrategyReq struct {
	FundCode string `json:"fund_code" binding:"required"`
}

type NAVQuery struct {
	Start string `form:"start"`
	End   string `form:"end"`
}

type SearchQuery struct {
	Q     string `form:"q" binding:"required"`
	Limit int    `form:"limit"`
}
