// Shapes in C++.
#pragma once
#include <string>

namespace geo {
namespace detail { int helper(); }

class Shape {
public:
    Shape() = default;
    virtual ~Shape();
    virtual double area() const = 0;
    static constexpr int kSides = 0;
protected:
    std::string name_;
private:
    int id_ = 0;
    void secret();
};

template <typename T>
struct Box : public Shape {
    T value;
    explicit Box(T v) : value{v}, extra_(0) { }
    double area() const override { return 0; }
    bool operator==(const Box& o) const { return value == o.value; }
private:
    int extra_;
};

enum class Mode : int { Fast, Slow };

using Id = long;

extern "C" {
int c_api(int x);
}

}  // namespace geo

double geo::Shape::area() const { return 1.0; }

geo::Shape::~Shape() {}

auto raw = R"json({"a": "}"})json";

int main(int argc, char** argv) {
    return 0;
}
