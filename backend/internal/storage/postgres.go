package storage

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"gateflow/internal/domain"
	"strings"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

type PostgresStore struct{ db *sql.DB }

func (s *PostgresStore) Migrate(ctx context.Context, schema string) error {
	_, err := s.db.ExecContext(ctx, schema)
	return err
}

func OpenPostgres(databaseURL string) (*PostgresStore, error) {
	db, err := sql.Open("pgx", databaseURL)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		db.Close()
		return nil, err
	}
	return &PostgresStore{db: db}, nil
}
func (s *PostgresStore) Close() error                     { return s.db.Close() }
func (s *PostgresStore) Health(ctx context.Context) error { return s.db.PingContext(ctx) }
func (s *PostgresStore) CreateTenant(ctx context.Context, value *domain.Tenant) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO tenants(id,name,status,created_at,updated_at) VALUES($1,$2,$3,$4,$5)`, value.ID, value.Name, value.Status, value.CreatedAt, value.UpdatedAt)
	return normalizeError(err)
}
func (s *PostgresStore) GetTenant(ctx context.Context, id string) (*domain.Tenant, error) {
	value := &domain.Tenant{}
	err := s.db.QueryRowContext(ctx, `SELECT id,name,status,created_at,updated_at FROM tenants WHERE id=$1`, id).Scan(&value.ID, &value.Name, &value.Status, &value.CreatedAt, &value.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	return value, err
}
func (s *PostgresStore) ListClients(ctx context.Context, tenantID string) ([]*domain.APIClient, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,tenant_id,name,api_key_prefix,api_key_hash,status,created_at,updated_at,last_used_at FROM api_clients WHERE tenant_id=$1 ORDER BY created_at`, tenantID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []*domain.APIClient{}
	for rows.Next() {
		value := &domain.APIClient{}
		var last sql.NullTime
		if err := rows.Scan(&value.ID, &value.TenantID, &value.Name, &value.KeyPrefix, &value.KeyHash, &value.Status, &value.CreatedAt, &value.UpdatedAt, &last); err != nil {
			return nil, err
		}
		if last.Valid {
			value.LastUsedAt = &last.Time
		}
		result = append(result, value)
	}
	return result, rows.Err()
}
func (s *PostgresStore) CreateClient(ctx context.Context, value *domain.APIClient) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO api_clients(id,tenant_id,name,api_key_prefix,api_key_hash,status,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, value.ID, value.TenantID, value.Name, value.KeyPrefix, value.KeyHash, value.Status, value.CreatedAt, value.UpdatedAt)
	return normalizeError(err)
}
func (s *PostgresStore) GetClientByID(ctx context.Context, tenantID, id string) (*domain.APIClient, error) {
	value := &domain.APIClient{}
	var last sql.NullTime
	err := s.db.QueryRowContext(ctx, `SELECT id,tenant_id,name,api_key_prefix,api_key_hash,status,created_at,updated_at,last_used_at FROM api_clients WHERE tenant_id=$1 AND id=$2`, tenantID, id).Scan(&value.ID, &value.TenantID, &value.Name, &value.KeyPrefix, &value.KeyHash, &value.Status, &value.CreatedAt, &value.UpdatedAt, &last)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if last.Valid {
		value.LastUsedAt = &last.Time
	}
	return value, err
}
func (s *PostgresStore) FindClientByPrefix(ctx context.Context, prefix string) (*domain.APIClient, error) {
	value := &domain.APIClient{}
	var last sql.NullTime
	err := s.db.QueryRowContext(ctx, `SELECT id,tenant_id,name,api_key_prefix,api_key_hash,status,created_at,updated_at,last_used_at FROM api_clients WHERE api_key_prefix=$1`, prefix).Scan(&value.ID, &value.TenantID, &value.Name, &value.KeyPrefix, &value.KeyHash, &value.Status, &value.CreatedAt, &value.UpdatedAt, &last)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if last.Valid {
		value.LastUsedAt = &last.Time
	}
	return value, err
}
func (s *PostgresStore) UpdateClient(ctx context.Context, value *domain.APIClient) error {
	_, err := s.db.ExecContext(ctx, `UPDATE api_clients SET name=$1,status=$2,api_key_prefix=$3,api_key_hash=$4,updated_at=$5 WHERE tenant_id=$6 AND id=$7`, value.Name, value.Status, value.KeyPrefix, value.KeyHash, value.UpdatedAt, value.TenantID, value.ID)
	return normalizeError(err)
}
func (s *PostgresStore) TouchClient(ctx context.Context, tenantID, id string, at time.Time) error {
	_, err := s.db.ExecContext(ctx, `UPDATE api_clients SET last_used_at=$1,updated_at=$1 WHERE tenant_id=$2 AND id=$3`, at, tenantID, id)
	return err
}
func routeArgs(value *domain.GatewayRoute) (string, error) {
	encoded, err := json.Marshal(value.AllowedMethods)
	return string(encoded), err
}
func scanRoute(scanner interface{ Scan(...any) error }) (*domain.GatewayRoute, error) {
	value := &domain.GatewayRoute{}
	var methods string
	if err := scanner.Scan(&value.ID, &value.TenantID, &value.Name, &value.GatewayPath, &value.UpstreamURL, &methods, &value.TimeoutMS, &value.AuthenticationRequired, &value.Active, &value.CreatedAt, &value.UpdatedAt); err != nil {
		return nil, err
	}
	if err := json.Unmarshal([]byte(methods), &value.AllowedMethods); err != nil {
		return nil, err
	}
	return value, nil
}

const routeColumns = `id,tenant_id,name,gateway_path,upstream_url,allowed_methods,timeout_ms,authentication_required,active,created_at,updated_at`

func (s *PostgresStore) ListRoutes(ctx context.Context, tenantID string) ([]*domain.GatewayRoute, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT `+routeColumns+` FROM gateway_routes WHERE tenant_id=$1 ORDER BY created_at`, tenantID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []*domain.GatewayRoute{}
	for rows.Next() {
		value, err := scanRoute(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, value)
	}
	return result, rows.Err()
}
func (s *PostgresStore) CreateRoute(ctx context.Context, value *domain.GatewayRoute) error {
	methods, err := routeArgs(value)
	if err != nil {
		return err
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO gateway_routes(id,tenant_id,name,gateway_path,upstream_url,allowed_methods,timeout_ms,authentication_required,active,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11)`, value.ID, value.TenantID, value.Name, value.GatewayPath, value.UpstreamURL, methods, value.TimeoutMS, value.AuthenticationRequired, value.Active, value.CreatedAt, value.UpdatedAt)
	return normalizeError(err)
}
func (s *PostgresStore) GetRoute(ctx context.Context, tenantID, id string) (*domain.GatewayRoute, error) {
	row := s.db.QueryRowContext(ctx, `SELECT `+routeColumns+` FROM gateway_routes WHERE tenant_id=$1 AND id=$2`, tenantID, id)
	value, err := scanRoute(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	return value, err
}
func (s *PostgresStore) UpdateRoute(ctx context.Context, value *domain.GatewayRoute) error {
	methods, err := routeArgs(value)
	if err != nil {
		return err
	}
	_, err = s.db.ExecContext(ctx, `UPDATE gateway_routes SET name=$1,gateway_path=$2,upstream_url=$3,allowed_methods=$4::jsonb,timeout_ms=$5,authentication_required=$6,active=$7,updated_at=$8 WHERE tenant_id=$9 AND id=$10`, value.Name, value.GatewayPath, value.UpstreamURL, methods, value.TimeoutMS, value.AuthenticationRequired, value.Active, value.UpdatedAt, value.TenantID, value.ID)
	return normalizeError(err)
}
func (s *PostgresStore) DeleteRoute(ctx context.Context, tenantID, id string) error {
	_, err := s.db.ExecContext(ctx, `DELETE FROM gateway_routes WHERE tenant_id=$1 AND id=$2`, tenantID, id)
	return normalizeError(err)
}
func (s *PostgresStore) FindRoute(ctx context.Context, tenantID, path string) (*domain.GatewayRoute, error) {
	row := s.db.QueryRowContext(ctx, `SELECT `+routeColumns+` FROM gateway_routes WHERE tenant_id=$1 AND active=true AND ($2= gateway_path OR $2 LIKE RTRIM(gateway_path,'/') || '/%') ORDER BY length(gateway_path) DESC LIMIT 1`, tenantID, path)
	value, err := scanRoute(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	return value, err
}
func (s *PostgresStore) GetPolicy(ctx context.Context, tenantID, clientID, routeID string) (*domain.RateLimitPolicy, error) {
	value := &domain.RateLimitPolicy{}
	var storedClientID, storedRouteID sql.NullString
	err := s.db.QueryRowContext(ctx, `SELECT id,tenant_id,api_client_id,route_id,bucket_capacity,refill_rate,enabled,created_at,updated_at FROM rate_limit_policies WHERE tenant_id=$1 AND enabled=true AND (api_client_id=$2 OR api_client_id IS NULL) AND (route_id=$3 OR route_id IS NULL) ORDER BY (api_client_id IS NULL)::int+(route_id IS NULL)::int LIMIT 1`, tenantID, clientID, routeID).Scan(&value.ID, &value.TenantID, &storedClientID, &storedRouteID, &value.Capacity, &value.RefillRate, &value.Enabled, &value.CreatedAt, &value.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	value.ClientID = storedClientID.String
	value.RouteID = storedRouteID.String
	return value, err
}
func (s *PostgresStore) UpsertPolicy(ctx context.Context, value *domain.RateLimitPolicy) error {
	result, err := s.db.ExecContext(ctx, `UPDATE rate_limit_policies SET bucket_capacity=$1,refill_rate=$2,enabled=$3,updated_at=$4 WHERE tenant_id=$5 AND api_client_id IS NOT DISTINCT FROM NULLIF($6,'') AND route_id IS NOT DISTINCT FROM NULLIF($7,'')`, value.Capacity, value.RefillRate, value.Enabled, value.UpdatedAt, value.TenantID, value.ClientID, value.RouteID)
	if err != nil {
		return err
	}
	if count, _ := result.RowsAffected(); count > 0 {
		return nil
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO rate_limit_policies(id,tenant_id,api_client_id,route_id,bucket_capacity,refill_rate,enabled,created_at,updated_at) VALUES($1,$2,NULLIF($3,''),NULLIF($4,''),$5,$6,$7,$8,$9)`, value.ID, value.TenantID, value.ClientID, value.RouteID, value.Capacity, value.RefillRate, value.Enabled, value.CreatedAt, value.UpdatedAt)
	return normalizeError(err)
}
func (s *PostgresStore) InsertLog(ctx context.Context, value *domain.RequestLog) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO request_logs(id,request_id,tenant_id,client_id,route_id,method,status_code,latency_ms,blocked,created_at) VALUES($1,$2,$3,NULLIF($4,''),NULLIF($5,''),$6,$7,$8,$9,$10)`, value.ID, value.RequestID, value.TenantID, value.ClientID, value.RouteID, value.Method, value.StatusCode, value.LatencyMS, value.Blocked, value.CreatedAt)
	return err
}
func (s *PostgresStore) Summary(ctx context.Context, tenantID string) (*domain.AnalyticsSummary, error) {
	value := &domain.AnalyticsSummary{}
	err := s.db.QueryRowContext(ctx, `SELECT count(*), count(*) FILTER(WHERE status_code>=200 AND status_code<400 AND NOT blocked), count(*) FILTER(WHERE blocked), COALESCE(avg(latency_ms),0), count(DISTINCT client_id) FILTER(WHERE client_id IS NOT NULL), COALESCE((SELECT r.name FROM request_logs l2 LEFT JOIN gateway_routes r ON r.id=l2.route_id AND r.tenant_id=l2.tenant_id WHERE l2.tenant_id=$1 GROUP BY r.name ORDER BY count(*) DESC LIMIT 1),'') FROM request_logs WHERE tenant_id=$1`, tenantID).Scan(&value.TotalRequests, &value.SuccessfulRequests, &value.BlockedRequests, &value.AverageResponseMS, &value.ActiveClients, &value.MostUsedRoute)
	return value, err
}
func (s *PostgresStore) Traffic(ctx context.Context, tenantID string) (*domain.TrafficAnalytics, error) {
	result := &domain.TrafficAnalytics{RequestsOverTime: []domain.TrafficPoint{}, StatusDistribution: []domain.StatusCount{}, ByClient: []domain.NamedCount{}, BlockedByRoute: []domain.NamedCount{}, LatencyTrend: []domain.TrafficPoint{}}
	rows, err := s.db.QueryContext(ctx, `SELECT to_char(date_trunc('hour',created_at),'YYYY-MM-DD"T"HH24:00:00"Z"'), count(*), round(avg(latency_ms)) FROM request_logs WHERE tenant_id=$1 GROUP BY 1 ORDER BY 1`, tenantID)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var point domain.TrafficPoint
		var average float64
		if err := rows.Scan(&point.Bucket, &point.Count, &average); err != nil {
			rows.Close()
			return nil, err
		}
		result.RequestsOverTime = append(result.RequestsOverTime, point)
		result.LatencyTrend = append(result.LatencyTrend, domain.TrafficPoint{Bucket: point.Bucket, Count: int64(average)})
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return nil, err
	}
	rows.Close()
	rows, err = s.db.QueryContext(ctx, `SELECT status_code,count(*) FROM request_logs WHERE tenant_id=$1 GROUP BY status_code ORDER BY status_code`, tenantID)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var value domain.StatusCount
		if err := rows.Scan(&value.StatusCode, &value.Count); err != nil {
			rows.Close()
			return nil, err
		}
		result.StatusDistribution = append(result.StatusDistribution, value)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return nil, err
	}
	rows.Close()
	rows, err = s.db.QueryContext(ctx, `SELECT COALESCE(c.name,'Unknown'),count(*) FROM request_logs l LEFT JOIN api_clients c ON c.id=l.client_id AND c.tenant_id=l.tenant_id WHERE l.tenant_id=$1 GROUP BY c.name ORDER BY count(*) DESC`, tenantID)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var value domain.NamedCount
		if err := rows.Scan(&value.Name, &value.Count); err != nil {
			rows.Close()
			return nil, err
		}
		result.ByClient = append(result.ByClient, value)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return nil, err
	}
	rows.Close()
	rows, err = s.db.QueryContext(ctx, `SELECT COALESCE(r.name,'Unknown'),count(*) FROM request_logs l LEFT JOIN gateway_routes r ON r.id=l.route_id AND r.tenant_id=l.tenant_id WHERE l.tenant_id=$1 AND l.blocked=true GROUP BY r.name ORDER BY count(*) DESC`, tenantID)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var value domain.NamedCount
		if err := rows.Scan(&value.Name, &value.Count); err != nil {
			rows.Close()
			return nil, err
		}
		result.BlockedByRoute = append(result.BlockedByRoute, value)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return nil, err
	}
	rows.Close()
	return result, nil
}
func (s *PostgresStore) ListLogs(ctx context.Context, tenantID string) ([]*domain.RequestLog, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id,request_id,tenant_id,COALESCE(client_id,''),COALESCE(route_id,''),method,status_code,latency_ms,blocked,created_at FROM request_logs WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT 500`, tenantID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []*domain.RequestLog{}
	for rows.Next() {
		value := &domain.RequestLog{}
		if err := rows.Scan(&value.ID, &value.RequestID, &value.TenantID, &value.ClientID, &value.RouteID, &value.Method, &value.StatusCode, &value.LatencyMS, &value.Blocked, &value.CreatedAt); err != nil {
			return nil, err
		}
		result = append(result, value)
	}
	return result, rows.Err()
}
func trafficFromRows(ctx context.Context, db *sql.DB, tenantID string) (*domain.TrafficAnalytics, error) {
	result := &domain.TrafficAnalytics{RequestsOverTime: []domain.TrafficPoint{}, StatusDistribution: []domain.StatusCount{}, ByClient: []domain.NamedCount{}, BlockedByRoute: []domain.NamedCount{}, LatencyTrend: []domain.TrafficPoint{}}
	rows, err := db.QueryContext(ctx, `SELECT to_char(date_trunc('hour',created_at),'YYYY-MM-DD"T"HH24:00:00"Z"'),count(*),round(avg(latency_ms)) FROM request_logs WHERE tenant_id=$1 GROUP BY 1 ORDER BY 1`, tenantID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		value := domain.TrafficPoint{}
		var average float64
		if err := rows.Scan(&value.Bucket, &value.Count, &average); err != nil {
			return nil, err
		}
		result.RequestsOverTime = append(result.RequestsOverTime, value)
		result.LatencyTrend = append(result.LatencyTrend, domain.TrafficPoint{Bucket: value.Bucket, Count: int64(average)})
	}
	return result, rows.Err()
}
func normalizeError(err error) error {
	if err == nil {
		return nil
	}
	if strings.Contains(strings.ToLower(err.Error()), "duplicate") || strings.Contains(strings.ToLower(err.Error()), "unique") || strings.Contains(strings.ToLower(err.Error()), "conflict") {
		return ErrConflict
	}
	if strings.Contains(fmt.Sprint(err), "no rows") {
		return ErrNotFound
	}
	return err
}
