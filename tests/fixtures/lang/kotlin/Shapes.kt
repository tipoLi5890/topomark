/* Shapes and helpers. */
package demo.shapes

import kotlin.math.PI

const val MAX = 3

/** A shape. */
sealed interface Shape {
    fun area(): Double
}

data class Circle(val r: Double) : Shape {
    override fun area(): Double = PI * r * r

    private fun secret() {
        val s = "brace { ${r.let { "}" }} "
    }

    companion object {
        fun unit() = Circle(1.0)
    }
}

class Square(
    val side: Double,
) : Shape
{
    override fun area() = side * side
    internal val label: String
        get() = """raw { ${side} """
}

enum class Kind(val n: Int) {
    A(1), B(2);

    fun twice() = n * 2
}

object Registry {
    @JvmStatic
    fun register(s: Shape) {}
}

fun Shape.describe(): String {
    return "area=${area()}"
}

typealias Shapes = List<Shape>

private fun hidden() = 'x'
