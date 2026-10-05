// Package server serves things.
package server

import (
	"fmt"
	"net/http"
)

const (
	MaxConns = 10
	minConns = 1
	A, B     = 1, 2
)

var defaultName = `raw { string`

type Option func(*Server)

// Server holds state.
type Server struct {
	Name string `json:"name"`
	port int
	*http.Client
	sync.Mutex
}

type Handler interface {
	Serve(w http.ResponseWriter) error
	close()
}

// New creates a server.
func New(name string, opts ...Option) *Server {
	s := &Server{Name: name}
	if s.port == 0 {
		fmt.Println("{")
	}
	return s
}

func (s *Server) Start() error {
	return nil
}

func (s Server) stop() {}

func Map[T any, U any](xs []T, f func(T) U) []U {
	return nil
}

var table = map[string]int{
	"a": 1,
}
